"""TeX in the manuscript's text, as `check` reports it.

The build asks pandoc how it reads the text and refuses TeX that the Word writer would
leave out (`tests/test_raw_tex.py`). `check` read the sources and passed such a text: the
number after a TeX sign was counted as printed by every gate, and an author learned of it
at the build. `check` now asks pandoc the same question where pandoc is installed, with the
text the build would hand it, so what it reports is what the build refuses and nothing
else. Where pandoc is not installed it says so once, in a note, and passes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project

#: A backslash and a line feed, written so that no tool between the author of a test and
#: this file can halve the first or read it as the start of an escape.
B = chr(92)
N = chr(10)
HELD = "The database contained {{results.cohort.n_reports}} reports, of which"
LEFT_OUT = (
    "which the Word writer leaves out of the document with whatever the command takes after it"
)
needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


def main_md(project: Path) -> Path:
    return project / "manuscript" / "main.md"


def supplement_md(project: Path) -> Path:
    return project / "manuscript" / "supplementary" / "S1_code_lists.md"


def write(project: Path, sentence: str, held: str = HELD) -> int:
    """Put `sentence` where the example's Results hold `held`, and return its first line."""
    source = main_md(project)
    text = source.read_bytes().decode("utf-8")
    assert text.count(held) == 1
    source.write_bytes(text.replace(held, sentence).encode("utf-8"))
    return text[: text.index(held)].count(N) + 1


def count(project: Path) -> str:
    """The example's first bound number, as the document prints it."""
    return load_namespace(load_project(project)[0])[0]["results.cohort.n_reports"].display


def checked(project: Path, capsys, *more: str) -> tuple[int, dict]:
    """`check --json`: its exit code and what it printed."""
    capsys.readouterr()
    code = main(["check", str(project), "--json", *more])
    return code, json.loads(capsys.readouterr().out)


def of(report: dict, code: str) -> list[dict]:
    return [finding for finding in report["findings"] if finding["code"] == code]


@pytest.fixture
def no_pandoc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A PATH that holds no pandoc."""
    empty = tmp_path / "an-empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert shutil.which("pandoc") is None


# ------------------------------------------------------------------------- what is reported


@needs_pandoc
def test_tex_in_the_text_fails_check_in_the_builds_sentence_at_its_line(
    project: Path, capsys
) -> None:
    """`The database contained \\approx {{results.cohort.n_reports}} reports` passed
    `check`: every gate counted the number as printed, and the build refused it. The
    finding is the build's sentence, at the line of the file."""
    line = write(project, HELD.replace("contained ", "contained " + B + "approx "))

    code, report = checked(project, capsys)

    assert code == 1
    [finding] = of(report, "tex-in-the-text")
    assert finding["gate"] == "BUILD"
    assert finding["severity"] == "fail"
    assert Path(finding["path"]) == main_md(project)
    assert finding["line"] == line
    assert finding["message"] == (
        f"pandoc reads as TeX `{B}approx {count(project)}` (main.md:{line}), {LEFT_OUT}"
    )
    assert "TeX that is meant for a PDF only goes in a code span marked `{=latex}`" in (
        finding["hint"]
    )
    assert not report["ok"]

    # The build says the same of it, in the same words, where the check is skipped.
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    said = capsys.readouterr().err
    assert f"{finding['message']}. {finding['hint']}" in said, said
    assert "`check` cannot see this" not in said, "it sees this one"
    assert "`check` reports it too, and fails for it from `drafting` on." in said


@needs_pandoc
def test_a_build_stops_at_the_check_and_names_the_line(project: Path, capsys) -> None:
    line = write(project, HELD.replace("contained ", "contained " + B + "approx "))
    capsys.readouterr()

    assert main(["build", str(project), "--offline"]) == 1

    said = capsys.readouterr().out
    assert f"main.md:{line}" in said
    assert f"pandoc reads as TeX `{B}approx {count(project)}`" in said
    assert "not building" in said
    assert not (project / "build" / "manuscript.docx").exists()


@needs_pandoc
def test_the_finding_fails_from_drafting_on_and_is_listed_before(project: Path, capsys) -> None:
    write(project, HELD.replace("contained ", "contained " + B + "approx "))

    early, report = checked(project, capsys, "--stage", "analysis")
    [finding] = of(report, "tex-in-the-text")
    assert finding["severity"] == "info"
    assert finding["message"].endswith("[not due until drafting]")
    assert early == 0, report

    for stage in ("drafting", "internal-review"):
        code, report = checked(project, capsys, "--stage", stage)
        assert code == 1, stage
        [finding] = of(report, "tex-in-the-text")
        assert finding["severity"] == "fail", stage


@needs_pandoc
def test_the_example_holds_none_and_says_how_many_documents_were_read(
    project: Path, capsys
) -> None:
    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "tex-in-the-text")
    assert not of(report, "tex-not-judged")
    assert not of(report, "tex-does-nothing")
    # The paper and its supplement: a pass over no document would read the same otherwise.
    assert report["counts"]["documents_read_for_tex"] == 2


#: What pandoc reads as no TeX, or as TeX the document loses nothing by.
KEPT = {
    "maths": HELD.replace("contained ", f"contained ${B}approx$ "),
    "a code span": f"Saved under `C:{B}Users{B}name`. " + HELD,
    "a doubled backslash": f"Saved under C:{B}{B}Users. " + HELD,
    "TeX marked for LaTeX": f"`{B}textit{{in vivo}}`{{=latex}} " + HELD,
    "a macro's definition": f"{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{N}" + HELD,
    "a comment": f"<!-- {B}approx 12 --> " + HELD,
}


@needs_pandoc
@pytest.mark.parametrize("case", list(KEPT))
def test_what_the_build_lets_pass_is_no_finding(case: str, project: Path, capsys) -> None:
    write(project, KEPT[case])

    _code, report = checked(project, capsys)

    assert not of(report, "tex-in-the-text"), case
    assert not of(report, "tex-does-nothing"), case
    assert not of(report, "gate-errored"), case


@needs_pandoc
def test_each_kind_is_one_finding_and_says_how_many_more_there_are(
    project: Path, capsys
) -> None:
    """Two pieces that read the same are found at one line, the first: so they are one
    finding, which counts the other. A piece that reads otherwise is a finding of its own,
    and the author has every kind in one run."""
    vivo = f"{B}textit{{in vivo}}"
    line = write(
        project,
        f"Measured {vivo} here. {HELD} IFN-{B}gamma was seen, {vivo} again, and",
    )

    code, report = checked(project, capsys)

    assert code == 1
    first, second = of(report, "tex-in-the-text")
    assert first["message"] == (
        f"pandoc reads as TeX `{vivo}` (main.md:{line}), and 1 more like it, {LEFT_OUT}"
    )
    assert second["message"] == f"pandoc reads as TeX `{B}gamma` (main.md:{line}), {LEFT_OUT}"


@needs_pandoc
def test_the_line_is_the_pieces_and_not_that_of_the_same_sign_in_maths_above(
    project: Path, capsys
) -> None:
    """The line was that of the first place the command stands in the file. A manuscript
    that writes the sign as maths in one sentence, as it is told to, and bare before a
    bound number further down was sent to the sentence that is right."""
    maths = f"About ${B}approx$ half were from clinicians."
    line = write(
        project,
        maths + N + N + HELD.replace("contained ", "contained " + B + "approx "),
    )

    code, report = checked(project, capsys)

    assert code == 1
    [finding] = of(report, "tex-in-the-text")
    assert finding["line"] == line + 2
    assert f"`{B}approx {count(project)}` (main.md:{line + 2})" in finding["message"]


#: Where a piece is looked for: the text as built holds it as pandoc read it, values in, and
#: the line is that of the same occurrence of its command in the file.
LOCATED = {
    "the second of two, the first in maths": (
        f"{B}approx 12",
        f"A ${B}approx$ b.{N}{N}Then {B}approx {{{{results.n}}}} of them.",
        f"A ${B}approx$ b.{N}{N}Then {B}approx 12 of them.",
        (0, 3),
    ),
    "the first of two": (
        f"{B}approx 12",
        f"Some {B}approx {{{{results.n}}}} here.{N}And ${B}approx$ there.",
        f"Some {B}approx 12 here.{N}And ${B}approx$ there.",
        (0, 1),
    ),
    "one a value puts there, after one in the file": (
        f"{B}approx 12",
        f"A ${B}approx$ b.{N}Then {{{{results.sign}}}} of them.",
        f"A ${B}approx$ b.{N}Then {B}approx 12 of them.",
        (0, None),
    ),
    "one no text holds as it is read, by its command": (
        f"{B}textit{{in vivo}} twice",
        f"One line.{N}Measured {B}textit{{in{N}vivo}} here.",
        f"One line.{N}Measured {B}textit{{in{N}vivo}} here.",
        (0, 2),
    ),
    # The build takes the file's own header off, so the text as built holds one fewer.
    "one the file's own header holds too": (
        f"{B}gamma",
        f"---{N}title: 'IFN-${B}gamma$'{N}---{N}{N}Release of IFN-{B}gamma was measured.",
        f"Release of IFN-{B}gamma was measured.",
        (0, 5),
    ),
    "one nothing holds": (f"{B}gamma", "No such letters.", "Nor here.", None),
}


@pytest.mark.parametrize("case", list(LOCATED))
def test_where_a_piece_is_looked_for(case: str) -> None:
    from manuscript_guard.build.reading import located

    piece, written, built, found = LOCATED[case]
    assert located(piece, [("main.md", written)], [built]) == found


@needs_pandoc
def test_tex_in_the_supplement_is_found_in_its_file(project: Path, capsys) -> None:
    source = supplement_md(project)
    text = source.read_bytes().decode("utf-8")
    added = text + N + f"Measured {B}textit{{in vivo}} throughout." + N
    source.write_bytes(added.encode("utf-8"))
    line = text.count(N) + 2

    code, report = checked(project, capsys)

    assert code == 1
    [finding] = of(report, "tex-in-the-text")
    assert Path(finding["path"]) == source
    assert finding["line"] == line
    assert f"(S1_code_lists.md:{line})" in finding["message"]


def test_tex_that_a_value_makes_is_found_with_no_line(project: Path) -> None:
    """A piece no source holds as written, where the text as built does: the finding is at
    the file, and says that a value or a table puts it there."""
    from manuscript_guard.build import tex_check

    found = tex_check.findings_of(
        [f"{B}approx 12"],
        [],
        [("main.md", "A value: {{results.x}}.")],
        [f"A value: {B}approx 12."],
        [main_md(project)],
    )

    [finding] = found
    assert finding.path == main_md(project)
    assert finding.line is None
    assert "(main.md, where a value or a table puts it)" in finding.message


def test_a_piece_no_text_holds_is_a_finding_at_no_file(project: Path) -> None:
    from manuscript_guard.build import tex_check

    [finding] = tex_check.findings_of(
        [f"{B}gamma "], [], [("main.md", "No such letters.")], ["Nor here."], [main_md(project)]
    )

    assert finding.path is None
    assert "(not found as written in a source: a macro or a value makes it)" in finding.message


def test_more_kinds_than_are_named_are_counted(project: Path) -> None:
    """A place is looked for through every source for each kind, so the kinds named are
    twenty, as for the warning, and the rest are counted in a finding of their own."""
    from manuscript_guard.build import tex_check

    kinds = [f"{B}kind{chr(97 + index // 26)}{chr(97 + index % 26)}" for index in range(23)]
    text = " ".join(kinds)

    files = [main_md(project)]

    found = tex_check.findings_of(kinds, [], [("main.md", text)], [text], files)

    assert len(found) == 21
    assert len(tex_check.findings_of(kinds[:20], [], [("main.md", text)], [text], files)) == 20
    assert {(finding.code, finding.severity) for finding in found} == {("tex-in-the-text", "fail")}
    # It has no file, so it is printed before the twenty: it says how many they are and
    # points at nothing "above".
    assert found[-1].message == (
        "pandoc reads 3 more kinds of TeX in the text than the twenty named, and the Word "
        "writer leaves each out of the document"
    )
    assert found[-1].hint == "each is named once the twenty that are named are put right"


# --------------------------------------------------------------------------- layout commands


@needs_pandoc
def test_a_layout_command_is_the_builds_warning_and_check_passes(project: Path, capsys) -> None:
    """A page break alone loses no word: the build warns that it does nothing in a Word
    document and makes one. `check` gives the same warning, at the line."""
    line = write(project, B + "newpage" + N + N + HELD)

    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "tex-in-the-text")
    [warning] = of(report, "tex-does-nothing")
    assert warning["severity"] == "warn"
    assert warning["gate"] == "BUILD"
    assert Path(warning["path"]) == main_md(project)
    assert warning["line"] == line
    assert warning["message"] == (
        f"`{B}newpage` (main.md:{line}) does nothing in a Word document"
    )

    assert main(["build", str(project), "--offline"]) == 0
    said = capsys.readouterr().out
    assert said.count(warning["message"]) == 1, said
    assert said.count(warning["hint"]) == 1, said


# ----------------------------------------------------------------------- where pandoc is not


def test_without_pandoc_the_example_passes_and_check_says_so_once(
    project: Path, capsys, no_pandoc: None
) -> None:
    code, report = checked(project, capsys)

    assert code == 0, report
    assert report["ok"]
    [note] = of(report, "tex-not-judged")
    assert note["severity"] == "info"
    assert note["gate"] == "BUILD"
    assert note["message"] == (
        "pandoc is not on PATH, so TeX in the text is not judged here: the build judges it"
    )
    assert "pandoc.org/installing" in note["hint"]
    assert report["counts"]["documents_read_for_tex"] == 0

    capsys.readouterr()
    assert main(["check", str(project)]) == 0
    said = capsys.readouterr().out
    assert said.count("TeX in the text is not judged here") == 1
    assert "0 failing" in said


def test_without_pandoc_tex_in_the_text_is_the_builds_to_judge(
    project: Path, capsys, no_pandoc: None
) -> None:
    """The exit code is that of a gate that passed, and the note is no finding of TeX: a
    machine tells it by its code and by its severity, which no failing finding carries."""
    write(project, HELD.replace("contained ", "contained " + B + "approx "))

    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "tex-in-the-text")
    [note] = of(report, "tex-not-judged")
    assert note["severity"] == "info"
    assert "[not due until" not in note["message"], "it is no finding put off to a later stage"
    assert not of(report, "gate-errored")


# ----------------------------------------------------------------------- how often pandoc runs


@needs_pandoc
def test_pandoc_reads_each_document_once_and_not_each_file(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run for the paper and one for its supplement, which the build makes as two
    documents, however many files each is written in."""
    from manuscript_guard.build import reading

    (project / "manuscript" / "acknowledgements.md").write_text(
        "# Acknowledgements" + N + N + "We thank the reporters." + N, encoding="utf-8"
    )
    (project / "manuscript" / "supplementary" / "S2_more.md").write_text(
        "# More" + N + N + "Nothing more." + N, encoding="utf-8"
    )
    runs: list[list[str]] = []
    run = subprocess.run

    def counted(command, *args, **kwargs):
        if "pandoc" in Path(command[0]).name:
            runs.append(list(command))
        return run(command, *args, **kwargs)

    monkeypatch.setattr(reading.subprocess, "run", counted)

    _code, report = checked(project, capsys)

    assert len(runs) == 2, runs
    assert report["counts"]["documents_read_for_tex"] == 2

    shutil.rmtree(project / "manuscript" / "supplementary")
    runs.clear()

    _code, report = checked(project, capsys)

    assert len(runs) == 1, runs
    assert report["counts"]["documents_read_for_tex"] == 1


# ------------------------------------------------------------------- what must not stop a check


@needs_pandoc
def test_a_title_no_document_can_carry_does_not_stop_the_reading(project: Path, capsys) -> None:
    """The build's header cannot be written for such a title, which `check` reports. The
    text is read all the same, under no header."""
    paper = project / "paper.yaml"
    text = paper.read_bytes().decode("utf-8")
    lines = text.split(N)
    [at] = [index for index, line in enumerate(lines) if line.startswith("title:")]
    lines[at] = 'title: "A study of ' + B + 'a signals"'
    paper.write_bytes(N.join(lines).encode("utf-8"))
    write(project, HELD.replace("contained ", "contained " + B + "approx "))

    code, report = checked(project, capsys)

    assert code == 1
    assert any("control character" in finding["message"] for finding in report["findings"])
    assert len(of(report, "tex-in-the-text")) == 1
    assert not of(report, "gate-errored")


@needs_pandoc
def test_a_text_nested_too_deep_to_walk_is_a_note_and_no_crash(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import reading

    def too_deep(source: str, pandoc: str, limit: float | None = None):
        raise RecursionError

    monkeypatch.setattr(reading, "tex_read", too_deep)

    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "gate-errored")
    notes = of(report, "tex-not-judged")
    assert len(notes) == 2, "the paper and its supplement"
    assert all(note["severity"] == "info" for note in notes)
    assert "nested too deep" in notes[0]["message"]


@needs_pandoc
def test_check_does_not_wait_for_pandoc_past_its_limit(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pandoc takes about three times as long for each level of brackets nested in
    brackets: a quarter of a second at six, thirteen seconds at ten, and at fourteen far
    longer than anyone waits. `check` ran it with no limit, where it had never waited on
    another program, and the suite's own check of prose someone might write did not end."""
    from manuscript_guard.build import tex_check

    monkeypatch.setattr(tex_check, "READ_SECONDS", 1.0)
    source = main_md(project)
    written = source.read_bytes().decode("utf-8")
    nested = "[" * 14 + "see the note" + "]" * 14
    source.write_bytes((written + N + nested + N).encode("utf-8"))

    started = time.perf_counter()
    code, report = checked(project, capsys)
    waited = time.perf_counter() - started

    assert waited < 30, f"check took {waited:.0f} s"
    assert code == 0, report
    assert not of(report, "gate-errored")
    [note] = of(report, "tex-not-judged")
    assert note["severity"] == "info"
    assert note["message"] == (
        "pandoc had not read the manuscript after 1 s, so TeX in it is not judged here: "
        "the build judges it, and waits for pandoc as long as it takes"
    )
    assert report["counts"]["documents_read_for_tex"] == 1, "the supplement was read"


def test_check_waits_ten_seconds_for_each_document() -> None:
    """Pandoc reads the example in a tenth of a second and its text two hundred times over,
    164,000 words, in two: ten is past any manuscript and short of a wait that looks like
    a hang."""
    from manuscript_guard.build import tex_check

    assert tex_check.READ_SECONDS == 10.0


@needs_pandoc
def test_each_document_is_read_under_the_limit(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import reading, tex_check

    limits: list[float | None] = []

    def read(source: str, pandoc: str, limit: float | None = None):
        limits.append(limit)
        return [], []

    monkeypatch.setattr(reading, "tex_read", read)

    checked(project, capsys)

    assert limits == [tex_check.READ_SECONDS, tex_check.READ_SECONDS]


def test_the_limit_is_given_to_the_run_of_pandoc(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import reading

    given: dict = {}

    def run(command, **how):
        given.update(how)
        return subprocess.CompletedProcess(command, 0, stdout=b'{"blocks": [], "meta": {}}')

    monkeypatch.setattr(reading.subprocess, "run", run)

    assert reading.tex_read("Some text.", "pandoc", 3.0) == ([], [])
    assert given["timeout"] == 3.0
    assert reading.tex_read("Some text.", "pandoc") == ([], [])
    assert given["timeout"] is None, "the build gives no limit"


def test_a_pandoc_that_cannot_be_started_is_a_note_and_no_crash(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file named pandoc on PATH that the system cannot run was `gate-errored`, which
    fails at every stage and calls itself a bug, where no pandoc at all is a note."""
    missing = str(project.parent / "no-such-folder" / "pandoc")
    which = shutil.which

    def found(name: str, *args, **kwargs):
        return missing if name == "pandoc" else which(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", found)

    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "gate-errored")
    notes = of(report, "tex-not-judged")
    assert len(notes) == 2, "the paper and its supplement"
    assert all(note["severity"] == "info" for note in notes)
    assert "pandoc could not be run on the manuscript" in notes[0]["message"]
    assert report["counts"]["documents_read_for_tex"] == 0


@needs_pandoc
def test_an_answer_from_pandoc_that_is_no_json_is_a_note_and_no_crash(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import reading

    run = subprocess.run

    def garbled(command, *args, **kwargs):
        if "pandoc" in Path(command[0]).name:
            return subprocess.CompletedProcess(command, 0, stdout=b"pandoc: out of memory")
        return run(command, *args, **kwargs)

    monkeypatch.setattr(reading.subprocess, "run", garbled)

    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "gate-errored")
    notes = of(report, "tex-not-judged")
    assert len(notes) == 2
    assert "pandoc could not be run on the manuscript" in notes[0]["message"]
    assert report["counts"]["documents_read_for_tex"] == 0


@needs_pandoc
def test_a_text_pandoc_cannot_read_is_a_note_and_no_crash(
    project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import reading

    monkeypatch.setattr(reading, "tex_read", lambda source, pandoc, limit=None: None)

    code, report = checked(project, capsys)

    assert code == 0, report
    assert not of(report, "gate-errored")
    notes = of(report, "tex-not-judged")
    assert len(notes) == 2
    assert "pandoc could not read" in notes[0]["message"]
    assert report["counts"]["documents_read_for_tex"] == 0
