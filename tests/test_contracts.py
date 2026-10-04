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


#: What the build folds into a space, and nothing else: the ends of a line as YAML reads
#: them. No test held the last two: taken out of the fold, every test passed.
FOLDED = {
    "line feed": chr(0x0A),
    "carriage return": chr(0x0D),
    "carriage return and line feed": chr(0x0D) + chr(0x0A),
    "next line": chr(0x85),
    "line separator": chr(0x2028),
    "paragraph separator": chr(0x2029),
}


@pytest.mark.parametrize("name", list(FOLDED))
def test_each_end_of_a_line_is_folded_into_a_space_and_is_no_finding(name: str) -> None:
    from manuscript_guard.contracts.project import one_line, unprintable_character

    text = f"First{FOLDED[name]}second"
    assert one_line(text) == "First second"
    assert unprintable_character(text) is None


def test_a_tab_is_kept_and_is_no_finding() -> None:
    from manuscript_guard.contracts.project import one_line, unprintable_character

    text = "a" + chr(9) + "b"
    assert one_line(text) == text
    assert unprintable_character(text) is None


@pytest.mark.parametrize("name", list(FOLDED))
@pytest.mark.parametrize("times", [1, 2])
def test_the_break_that_closes_a_value_is_taken_off_and_not_made_a_space(
    name: str, times: int
) -> None:
    """A block ends with one. Folded into a space it stood after `al.`, where pandoc reads a
    space as a no-break space and printed one after the title, and after a closing
    backslash, which made the space a no-break one."""
    from manuscript_guard.contracts.project import one_line

    assert one_line("Smith et al." + FOLDED[name] * times) == "Smith et al."
    assert one_line(FOLDED[name] + "Smith et al.") == " Smith et al.", "only the closing one"


#: A character that is not a control character and that no document can carry either: half
#: of a pair, which two `\\u` escapes written as JSON writes them make, and the two code
#: points that are no character. What `check` calls each.
NOT_CARRIED = {
    "half of a pair": (chr(0xD83D), "the surrogate U+D83D"),
    "the other half": (chr(0xDE00), "the surrogate U+DE00"),
    "U+FFFE": (chr(0xFFFE), "the non-character U+FFFE"),
    "U+FFFF": (chr(0xFFFF), "the non-character U+FFFF"),
    "a control character": (chr(7), "the control character U+0007"),
}


@pytest.mark.parametrize("name", list(NOT_CARRIED))
def test_a_character_no_document_can_carry_is_named_for_what_it_is(name: str) -> None:
    from manuscript_guard.contracts.project import named, unprintable_character

    character, called = NOT_CARRIED[name]
    assert unprintable_character(f"a{character}b") == character
    assert named(character) == called


@pytest.mark.parametrize(
    "character", [chr(0x1F600), chr(0xE000), chr(0xFFFD), chr(0xA0), chr(0xD7FF), "é", "中"]
)
def test_a_character_a_document_can_carry_is_no_finding(character: str) -> None:
    from manuscript_guard.contracts.project import unprintable_character

    assert unprintable_character(f"a{character}b") is None


#: The same through `paper.yaml`, where an escape between double quotation marks makes each.
#: The first passed `check`, and the build stopped in pandoc's words about a file the author
#: never wrote; the second passed `check` too, and the build ended in a traceback.
ESCAPED = {
    "a non-character": ('title: "a\\uFFFFb"' + chr(10), "title", "the non-character U+FFFF"),
    "a pair written as JSON writes it": (
        'short_title: "\\ud83d\\ude00 smile"' + chr(10),
        "short_title",
        "the surrogate U+D83D",
    ),
}


@pytest.mark.parametrize("case", list(ESCAPED))
def test_an_escape_that_makes_no_character_is_a_finding_at_the_key(
    case: str, tmp_path: Path
) -> None:
    written, where, called = ESCAPED[case]
    paper = PAPER if where != "title" else PAPER.replace('title: "A study"' + chr(10), "")
    _project, report = load_project(a_project(tmp_path / "paper", paper + written))

    found = [f for f in report.failures if "no document can carry" in f.message]
    assert [(f.code, f.message.split(",")[0]) for f in found] == [
        ("schema-violation", f"{where}: holds {called}")
    ]


#: `paper.yaml` as raw text. Between double quotation marks YAML reads `\\n`, `\\r`,
#: `\\t`, `\\N`, `\\L` and `\\P` as the end of a line or a tab, so TeX that begins with one
#: loses its first letter in the document: `"$\\nu$"` was printed `$ u$`, through `check`
#: and the build. A real line break or tab cannot be refused, so the escape is looked for
#: in the file as written. Where the finding is, and the escape it names.
LOST_LETTER = {
    "nu in a title": ('title: "The $\\nu$ frequency"' + chr(10), "title", "\\nu"),
    "rho in a short title": ('short_title: "$\\rho$ and more"' + chr(10), "short_title", "\\rho"),
    "tau in a keyword": (
        'keywords:' + chr(10) + '  - plain' + chr(10) + '  - "$\\tau$ protein"' + chr(10),
        "keywords/1",
        "\\tau",
    ),
    "Lambda": ('short_title: "$\\Lambda$"' + chr(10), "short_title", "\\Lambda"),
    "Pi": ('short_title: "$\\Pi$"' + chr(10), "short_title", "\\Pi"),
    "Nu": ('keywords: ["a", "$\\Nu$"]' + chr(10), "keywords/1", "\\Nu"),
    "one keyword": ('keywords: "$\\nabla$ operator"' + chr(10), "keywords", "\\nabla"),
}


@pytest.mark.parametrize("case", list(LOST_LETTER))
def test_an_escape_that_takes_the_first_letter_of_a_word_is_a_finding_at_the_key(
    case: str, tmp_path: Path
) -> None:
    written, where, escape = LOST_LETTER[case]
    paper = PAPER if where != "title" else PAPER.replace('title: "A study"' + chr(10), "")
    _project, report = load_project(a_project(tmp_path / "paper", paper + written))

    found = [f for f in report.failures if "between double quotation marks" in f.message]
    assert [f.code for f in found] == ["schema-violation"]
    (finding,) = found
    assert finding.gate == "G0"
    assert finding.message.startswith(f"{where}: `{escape}` between double quotation marks")
    text = paper + written
    assert finding.line == text[: text.index(escape)].count(chr(10)) + 1
    assert "single quotation marks" in finding.hint


#: The same letters where nothing is lost, and so nothing is found: where a backslash is
#: a backslash, and where the break is not before a letter or is a break in the file.
KEPT_LETTER = {
    "single quotation marks": "short_title: 'The $\\nu$ frequency'" + chr(10),
    "no quotation marks": "short_title: The $\\nu$ frequency" + chr(10),
    "a doubled backslash": 'short_title: "The $\\\\nu$ frequency"' + chr(10),
    "a block": "short_title: |" + chr(10) + "  The $\\nu$ frequency" + chr(10),
    "a break before a space": 'short_title: "First\\n second"' + chr(10),
    "a break before a digit": 'short_title: "Table\\n2"' + chr(10),
    "a break in the file": 'short_title: "First' + chr(10) + '  second"' + chr(10),
    "a key the build does not print": 'target_journal: "the\\nu journal"' + chr(10),
}


@pytest.mark.parametrize("case", list(KEPT_LETTER))
def test_a_backslash_that_is_a_backslash_and_a_break_that_takes_no_letter_are_no_finding(
    case: str, tmp_path: Path
) -> None:
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + KEPT_LETTER[case]))
    assert report.failures == ()


def test_the_hint_names_a_space_where_a_line_break_was_meant(tmp_path: Path) -> None:
    """Followed where a break was meant, either way of keeping the letter loses the word:
    between single quotation marks `First part:\\nsecond part` holds a backslash, and pandoc
    reads `\\nsecond` as TeX and drops it. So the finding also says what to write then."""
    written = 'short_title: "First part:\\nsecond part"' + chr(10)
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = [f for f in report.failures if "between double quotation marks" in f.message]
    assert "single quotation marks" in finding.hint
    assert "where a line break or a tab was meant, write a space" in finding.hint


#: Text of the file that the value does not hold, and a value YAML does not keep. The
#: place a value is read from began at its anchor or its tag, so a comment after one was
#: read as the value; and a key written twice was read twice, where YAML keeps the last.
NOT_THE_VALUE = {
    "a comment after an anchor": (
        'short_title: &t  # the anchor for \\nu' + chr(10) + '  "A plain title"' + chr(10)
    ),
    "a comment after a tag": (
        'short_title: !!str  # see \\rho' + chr(10) + '  "A plain title"' + chr(10)
    ),
    "a comment after a keyword's anchor": (
        'keywords:' + chr(10) + '  - &k # \\nabla' + chr(10) + '    "plain"' + chr(10)
    ),
    "a key written twice, the last kept": (
        'short_title: "The $\\nu$ one"' + chr(10) + "short_title: 'The $\\nu$ one'" + chr(10)
    ),
}


@pytest.mark.parametrize("case", list(NOT_THE_VALUE))
def test_what_the_value_does_not_hold_is_not_read_for_a_lost_letter(
    case: str, tmp_path: Path
) -> None:
    from manuscript_guard.contracts.project import lost_letters

    root = a_project(tmp_path / "paper", PAPER + NOT_THE_VALUE[case])
    assert lost_letters(root / "paper.yaml") == []


def test_of_a_key_written_twice_the_one_yaml_keeps_is_read(tmp_path: Path) -> None:
    from manuscript_guard.contracts.project import lost_letters

    written = "short_title: 'The $\\nu$ one'" + chr(10) + 'short_title: "The $\\nu$ one"' + chr(10)
    root = a_project(tmp_path / "paper", PAPER + written)
    assert [(lost.where, lost.line) for lost in lost_letters(root / "paper.yaml")] == [
        ("short_title", 5)
    ]


def test_folding_a_run_of_line_breaks_takes_time_in_proportion(assert_linear) -> None:
    """The closing break was taken off with a pattern that tried every break of a run in
    the middle as the start of the end: 16,000 breaks took four and a half seconds, in
    `check` and in the hook at the start of a session."""
    from manuscript_guard.contracts.project import one_line

    assert_linear(lambda n: "a" + chr(10) * n + "b", one_line, 2000, "folding a run of breaks")


#: Each written between double quotation marks, as YAML reads them: `\a` is U+0007, `\e`
#: U+001B. The place `check` names and the character it names there.
CONTROL = {
    "title": ('title: "Effects of \\alpha-blockers"\n', "title", "U+0007"),
    "short title": ('short_title: "\\alpha-blockers"\n', "short_title", "U+0007"),
    "keyword": ('keywords:\n  - plain\n  - "\\escape"\n', "keywords/1", "U+001B"),
    "one keyword": ('keywords: "\\alpha"\n', "keywords", "U+0007"),
    # Control characters a line split takes for the end of a line, which YAML and pandoc
    # do not: `\v` and `\f` begin TeX's `\varepsilon` and `\frac`.
    "vertical tab": ('short_title: "The $\\varepsilon$ coefficient"\n', "short_title", "U+000B"),
    "form feed": ('keywords: ["$\\frac{a}{b}$"]\n', "keywords/0", "U+000C"),
    "file separator": ('keywords: ["before\\x1cafter"]\n', "keywords/0", "U+001C"),
    "record separator": ('short_title: "before\\x1eafter"\n', "short_title", "U+001E"),
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
    """YAML's own line breaks are folded by the build, not refused: a line feed, YAML's
    `\\N`, `\\L` and `\\P` (U+0085, U+2028, U+2029), and a tab is a tab. Each escape
    stands before a space here: before a letter it takes the letter, which is a finding
    of another kind (`LOST_LETTER`)."""
    written = (
        'short_title: "First\nsecond\\N third\\L fourth\\P fifth"\n'
        'keywords: ["a\tb"]\n'
    )
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))
    assert report.failures == ()


#: A backslash and a line feed, written so that no tool between the author of a test and
#: this file can halve the one or read either as the start of an escape.
BACKSLASH = chr(92)
LF = chr(10)

#: `paper.yaml` as raw text, with TeX that stands outside dollar signs in what the build
#: prints. Pandoc reads a title as Markdown and keeps TeX only as maths: `IFN-\gamma
#: release assays` passed `check` and a checked build and was printed `IFN-release assays`,
#: and `12 \pm 3 months` was printed without its `3`. Where the finding is, and what it
#: says.
TEX_OUTSIDE = {
    "a title between single quotation marks": (
        "title: 'IFN-" + BACKSLASH + "gamma release assays'" + LF,
        "title",
        "`" + BACKSLASH + "gamma` stands outside dollar signs",
    ),
    "a title with no quotation marks": (
        "title: IFN-" + BACKSLASH + "gamma release assays" + LF,
        "title",
        "`" + BACKSLASH + "gamma` stands outside dollar signs",
    ),
    "a title between double ones, the backslash doubled": (
        'title: "IFN-' + BACKSLASH * 2 + 'gamma release assays"' + LF,
        "title",
        "`" + BACKSLASH + "gamma` stands outside dollar signs",
    ),
    "a short title with a number after the command": (
        "short_title: 'Outcomes at 12 " + BACKSLASH + "pm 3 months'" + LF,
        "short_title",
        "`" + BACKSLASH + "pm` stands outside dollar signs",
    ),
    "a keyword": (
        "keywords:" + LF + "  - plain" + LF + "  - 'TNF" + BACKSLASH + "alpha signalling'" + LF,
        "keywords/1",
        "`" + BACKSLASH + "alpha` stands outside dollar signs",
    ),
    "one keyword": (
        "keywords: 'TNF" + BACKSLASH + "alpha'" + LF,
        "keywords",
        "`" + BACKSLASH + "alpha` stands outside dollar signs",
    ),
    "a block": (
        "short_title: |" + LF + "  A " + BACKSLASH + "textit{in vivo} study" + LF,
        "short_title",
        "`" + BACKSLASH + "textit` stands outside dollar signs",
    ),
    "a title over two lines, the dollar signs on the first": (
        "short_title: 'The $x$" + LF + "  and " + BACKSLASH + "gamma'" + LF,
        "short_title",
        "`" + BACKSLASH + "gamma` stands outside dollar signs",
    ),
    # Past a sign that can hold a dollar sign which opens nothing, maths is not read.
    "maths after a bracket": (
        "short_title: '[18F]FDG and TGF-$" + BACKSLASH + "beta$'" + LF,
        "short_title",
        "`" + BACKSLASH + "beta` stands after a `[`",
    ),
    "code around the dollar signs": (
        "short_title: '`$` " + BACKSLASH + "gamma `$`'" + LF,
        "short_title",
        "`" + BACKSLASH + "gamma` stands after a backtick",
    ),
}


@pytest.mark.parametrize("case", list(TEX_OUTSIDE))
def test_tex_outside_dollar_signs_in_what_the_document_prints_is_a_finding_at_the_key(
    case: str, tmp_path: Path
) -> None:
    written, where, says = TEX_OUTSIDE[case]
    paper = PAPER if where != "title" else PAPER.replace('title: "A study"' + LF, "")
    _project, report = load_project(a_project(tmp_path / "paper", paper + written))

    # One keyword where a list is expected is also the schema's finding for its shape.
    found = [f for f in report.failures if " stands " in f.message]
    assert [f.code for f in found] == ["schema-violation"]
    (finding,) = found
    assert finding.gate == "G0"
    assert finding.message.startswith(f"{where}: {says}")
    assert "between dollar signs" in finding.hint


def test_the_finding_says_what_the_document_loses_and_what_to_write(tmp_path: Path) -> None:
    written = "short_title: 'IFN-" + BACKSLASH + "gamma release assays'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    gamma = BACKSLASH + "gamma"
    assert finding.message == (
        f"short_title: `{gamma}` stands outside dollar signs, and the document is printed "
        f"without it; if it is maths, write `${gamma}$`"
    )
    # A command takes what follows it as TeX would, a number for one; and not every
    # backslash was meant as TeX.
    assert "the number" in finding.hint
    assert "`*in vivo*`" in finding.hint


def test_past_a_sign_the_finding_says_how_to_have_the_maths_read(tmp_path: Path) -> None:
    """`[18F]FDG and TGF-$\\beta$` is printed whole, and reported all the same: a bracket can
    hold a dollar sign that opens no maths, in a link's address for one, and the rule reads
    no maths past it. The finding must not say the TeX stands outside dollar signs, which
    it does not; it says what to write so that the maths is read."""
    written = "short_title: '[18F]FDG and TGF-$" + BACKSLASH + "beta$'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert "outside dollar signs" not in finding.message
    assert "may be printed without it" in finding.message
    assert "put a backslash before" in finding.message

    escaped = written.replace("[18F]", BACKSLASH + "[18F" + BACKSLASH + "]")
    _project, report = load_project(a_project(tmp_path / "mended", PAPER + escaped))
    assert report.failures == ()


def test_a_command_with_braces_is_not_told_to_stand_between_dollar_signs(tmp_path: Path) -> None:
    """The finding said to write the command between dollar signs whatever followed it.
    Followed for `Injury \\textit{in vivo} and after`, that is `$\\textit${in vivo}`, which
    passes `check` and is printed as typed, dollar signs and all. Where braces follow the
    command the finding gives no such remedy, and the hint has the ones that work."""
    written = "short_title: 'Injury " + BACKSLASH + "textit{in vivo} and after'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert finding.message == (
        f"short_title: `{BACKSLASH}textit` stands outside dollar signs, and the document is "
        "printed without it and what its braces hold"
    )
    assert "`*in vivo*`" in finding.hint and "`^18^`" in finding.hint


#: Titles whose TeX stands between dollar signs that pandoc reads no maths in, so "outside
#: dollar signs" would be false of them and "write `$...$`" would tell the author to write
#: what is there. `TGF-$\beta$1 signalling` is printed `TGF-$$1 signalling`. What the
#: finding says of each, and the title mended as it says, which passes.
NO_MATHS = {
    "a digit after the closing dollar sign": (
        "TGF-$" + BACKSLASH + "beta$1 signalling in fibrosis",
        "a digit follows the next `$`",
        "TGF-$" + BACKSLASH + "beta_1$ signalling in fibrosis",
    ),
    "a number after it, mended with a space": (
        "Adults aged $" + BACKSLASH + "geq$65 years",
        "a digit follows the next `$`",
        "Adults aged $" + BACKSLASH + "geq$ 65 years",
    ),
    # The command is not the first thing after the dollar sign: it was told it stood
    # outside dollar signs, and to write itself between them.
    "a command second after the dollar sign": (
        "Risk at $p " + BACKSLASH + "leq$0.05",
        "a digit follows the next `$`",
        "Risk at $p " + BACKSLASH + "leq 0.05$",
    ),
    # The next dollar sign is money, and no closing one: "take the space out" was no help.
    "a dollar amount after the command": (
        "IFN-$" + BACKSLASH + "gamma release and $5 a dose",
        "a space stands before the next `$`",
        "IFN-$" + BACKSLASH + "gamma$ release and " + BACKSLASH + "$5 a dose",
    ),
    "a dollar amount before it": (
        "Costs at $50,000 per QALY of TNF-$" + BACKSLASH + "alpha$ inhibitors",
        "an earlier `$`",
        "Costs at " + BACKSLASH + "$50,000 per QALY of TNF-$" + BACKSLASH + "alpha$ inhibitors",
    ),
    "a space before the closing dollar sign": (
        "IFN-$" + BACKSLASH + "gamma $ release",
        "a space stands before the next `$`",
        "IFN-$" + BACKSLASH + "gamma$ release",
    ),
    "no closing dollar sign": (
        "IFN-$" + BACKSLASH + "gamma release",
        "no `$` follows to close it",
        "IFN-$" + BACKSLASH + "gamma$ release",
    ),
}


@pytest.mark.parametrize("case", list(NO_MATHS))
def test_tex_between_dollar_signs_that_are_no_maths_is_said_to_be_so(
    case: str, tmp_path: Path
) -> None:
    title, says, mended = NO_MATHS[case]
    written = "short_title: '" + title + "'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert says in finding.message
    assert "outside dollar signs" not in finding.message
    assert "the document is printed without it" in finding.message
    assert BACKSLASH + "$` for a dollar sign" in finding.hint

    written = "short_title: '" + mended + "'" + LF
    _project, report = load_project(a_project(tmp_path / "mended", PAPER + written))
    assert report.failures == ()


def test_a_keyword_is_told_to_hold_the_character_and_not_maths(tmp_path: Path) -> None:
    """A keyword is printed in the document's properties and nowhere else, and maths is
    written there as its TeX: `TNF$\\alpha$ signalling` gives the keyword `TNF\\alpha
    signalling`. So for a keyword the finding says to type the character."""
    written = "keywords:" + LF + "  - 'TNF" + BACKSLASH + "alpha signalling'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert finding.message.startswith(
        f"keywords/0: `{BACKSLASH}alpha` stands outside dollar signs, and the document is "
        "printed without it; write it as text and not as maths, the character itself for a "
        "letter or a sign"
    )
    assert "write `$" not in finding.message


def test_a_keyword_that_is_no_character_is_not_told_to_type_one(tmp_path: Path) -> None:
    """A keyword with braces after its command was told to "type the character it stands
    for", where there is none: for `\\textit{in vivo}` what works is the hint's
    `*in vivo*`, which the properties carry as `in vivo`."""
    written = "keywords:" + LF + "  - 'studies " + BACKSLASH + "textit{in vivo}'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert "what its braces hold" in finding.message
    assert "write it as text and not as maths" in finding.message
    assert "`*in vivo*`" in finding.hint


def test_past_a_sign_a_keyword_is_not_told_to_escape_the_sign(tmp_path: Path) -> None:
    """With the sign escaped the maths is read, and a keyword's maths is printed as its
    TeX: the one remedy for a keyword is the character."""
    written = "keywords:" + LF + "  - '[18F]FDG and TGF-$" + BACKSLASH + "beta$'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert "may be printed without it" in finding.message
    assert "type the character the command stands for" in finding.message
    assert "put a backslash before" not in finding.message


def test_past_a_sign_a_command_with_braces_is_not_told_to_type_a_character(
    tmp_path: Path,
) -> None:
    written = "short_title: '[a] " + BACKSLASH + "textit{in vivo} study'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert "put a backslash before it" in finding.message
    assert "type the character" not in finding.message


def test_a_reference_in_a_superscript_is_a_finding_of_its_own(tmp_path: Path) -> None:
    """`IFN-^&bsol;gamma^ release` was printed `IFN- release`: pandoc resolves the
    references in what a superscript holds and reads the result again, once more for each
    script around it. Two attempts to resolve them as pandoc does each passed a value it
    drops TeX from, so the reference itself is the finding, whatever it stands for."""
    written = "short_title: 'IFN-^&bsol;gamma^ release'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert finding.message == (
        "short_title: `&bsol;` may be a character reference where a subscript or a "
        "superscript can hold it: pandoc resolves one there and reads the result again, so "
        "it can make TeX that the document is printed without; type the character itself, "
        "or put a space before the `&`"
    )

    written = "short_title: 'IFN-^" + chr(0x3B3) + "^ release and R&D; more'" + LF
    _project, report = load_project(a_project(tmp_path / "mended", PAPER + written))
    assert report.failures == ()


def test_an_ampersand_that_is_no_reference_is_not_called_one(tmp_path: Path) -> None:
    """`R^2^&RMSE; model fit` was told "`&RMSE;` is a character reference in a subscript or
    a superscript ... type the character itself". It is no reference, it stands after the
    superscript, and there is no character to type: the rule reports an `&` that a `;`
    follows wherever a script could hold it, and does not read it to see what it is. The
    sentence says no more than that, and names what mends this one, a space."""
    written = "short_title: 'R^2^&RMSE; model fit'" + LF
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert "`&RMSE;` may be a character reference" in finding.message
    assert "is a character reference" not in finding.message
    assert "put a space before the `&`" in finding.message

    written = "short_title: 'R^2^ &RMSE; model fit'" + LF
    _project, report = load_project(a_project(tmp_path / "mended", PAPER + written))
    assert report.failures == ()


def test_past_a_sign_a_keyword_with_braces_is_told_to_write_it_as_text(tmp_path: Path) -> None:
    """Without that it was given no remedy at all, and no test noticed."""
    written = (
        "keywords:" + LF + "  - '[18F] " + BACKSLASH + "textit{in vivo} uptake'" + LF
    )
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (finding,) = report.failures
    assert finding.message.endswith("; write it as text and not as maths")


#: The same where nothing is lost, and so nothing is found: TeX between dollar signs, a
#: backslash that is no TeX, and a backslash in what the build does not print.
TEX_KEPT = {
    "maths": "short_title: 'IFN-$" + BACKSLASH + "gamma$ release assays'" + LF,
    "maths between double quotation marks, the backslash doubled": (
        'short_title: "IFN-$' + BACKSLASH * 2 + 'gamma$ release"' + LF
    ),
    "maths in a keyword": "keywords: ['$" + BACKSLASH + "alpha$-synuclein', plain]" + LF,
    "a doubled backslash, printed as one": (
        "short_title: 'The command " + BACKSLASH * 2 + "gamma'" + LF
    ),
    "escaped signs": "short_title: 'Up 5" + BACKSLASH + "% in A" + BACKSLASH + "&B'" + LF,
    "a subscript before maths": (
        "short_title: 'HbA~1c~ and TGF-$" + BACKSLASH + "beta$'" + LF
    ),
    "a key the build does not print": (
        "target_journal: 'the" + BACKSLASH + "gamma journal'" + LF
    ),
    "a convention's pattern": (
        "conventions:" + LF
        + "  - pattern: '" + BACKSLASH + "bICD-10" + BACKSLASH + "b'" + LF
        + "    why: the name of a classification" + LF
    ),
}


@pytest.mark.parametrize("case", list(TEX_KEPT))
def test_tex_between_dollar_signs_and_a_backslash_that_is_no_tex_are_no_finding(
    case: str, tmp_path: Path
) -> None:
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + TEX_KEPT[case]))
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
