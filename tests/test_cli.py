"""The command line: exit codes, and the refusals that only exist there.

Added after a coverage audit found cli.py at 14%, and confirmed by mutation that the most
important refusal in the toolkit was untested: disabling the guard that stops `submit`
assembling a pack while the submission check fails broke no test at all.

Exit codes are part of the contract — hooks and CI read them — so they are asserted rather
than assumed.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

from manuscript_guard.cli import build_parser, main
from manuscript_guard.emit import write_digest

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def run(*argv: str) -> int:
    return main(list(argv))


# ---------------------------------------------------------------- check


def test_check_exits_zero_on_a_clean_project(project: Path, capsys) -> None:
    assert run("check", str(project)) == 0
    assert "0 failing" in capsys.readouterr().out


def test_check_exits_one_when_a_gate_fails(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nAn unbound number: 4321.\n", encoding="utf-8"
    )
    assert run("check", str(project)) == 1
    out = capsys.readouterr().out
    assert "[FAIL] G2" in out
    assert "'4321' is not bound to any source" in out


def test_check_json_carries_the_finding_code(project: Path, capsys) -> None:
    """The rendered report shows gate and message; --json is where a machine reads codes."""
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nAn unbound number: 4321.\n", encoding="utf-8"
    )
    assert run("check", str(project), "--json") == 1
    payload = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in payload["findings"]}
    assert "unclassified-number" in codes


def test_check_reports_the_stage_it_ran_at(project: Path, capsys) -> None:
    assert run("check", str(project), "--stage", "analysis") == 0
    assert "stage: analysis" in capsys.readouterr().out


def test_check_outside_a_project_exits_two(tmp_path: Path, capsys) -> None:
    """Cannot-run is a different answer from failed, and CI needs to tell them apart."""
    assert run("check", str(tmp_path)) == 2
    assert "no paper.yaml" in capsys.readouterr().err


#: A file read before any gate runs, left so that it cannot be used, and what is said of it.
#: Each ended `check` in a traceback and exit 1, which a hook takes for a fault of the tool.
CANNOT_BE_USED = {
    "utf-16": ("results/hand.json", b"\xff\xfe\x7b", "hand.json: cannot read as UTF-8"),
    "code page": (
        "authors.yaml",
        "authors:\n  - name: Renée\n".encode("cp1252"),
        "authors.yaml: cannot read as UTF-8: the byte 0xe9 on line 2",
    ),
    "ledger": (
        "literature/ledger.yaml",
        b"\xff\xfeentries: []\n",
        "ledger.yaml: cannot read as UTF-8",
    ),
    "list": ("paper.yaml", b"- a\n- b\n", "paper.yaml: holds a list where"),
    "paths": ("paper.yaml", b"paths: [results]\n", "paper.yaml: `paths` holds a list where"),
    "date": (
        "literature/ledger.yaml",
        b"entries:\n  - verified_on: 2026-09-31\n",
        "ledger.yaml: cannot parse: ",
    ),
}


@pytest.mark.parametrize("flags", [(), ("--submission",)], ids=["draft", "submission"])
@pytest.mark.parametrize("case", list(CANNOT_BE_USED))
def test_check_says_in_a_sentence_which_file_it_cannot_use(
    case: str, flags: tuple[str, ...], project: Path, capsys
) -> None:
    """Exit 2 and one sentence on stderr, as for a file that does not parse."""
    relative, content, said = CANNOT_BE_USED[case]
    (project / relative).write_bytes(content)

    assert run("check", str(project), *flags) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("manuscript-guard: ")
    assert said in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == "", "no gate ran, so there is no report"


def test_check_says_which_stage_is_not_one(project: Path, capsys) -> None:
    """The stage decides which findings fail; without it there is no verdict to give."""
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8") + "\nstage: draft\n", encoding="utf-8")

    assert run("check", str(project)) == 2
    assert "paper.yaml: `stage` is 'draft', which is not a stage" in capsys.readouterr().err

    # Told the stage, the check runs, and reports the line as a finding among the rest.
    assert run("check", str(project), "--submission") == 1
    assert "'draft' is not one of" in capsys.readouterr().out


def in_a_code_page(path: Path) -> int:
    """Leave a manuscript file as an editor that writes "ANSI" does: one accented letter in
    code page 1252, on a line of its own at the end. Returns the line it is on."""
    data = path.read_bytes()
    assert data.endswith(b"\n")
    path.write_bytes(data + b"\nCaf\xe9 society.\n")
    return data.count(b"\n") + 2


#: Every command that reads the text of the manuscript and is not `check`. Each ended in a
#: traceback (`UnicodeDecodeError`) and exit 1 on a file that is not UTF-8.
READS_THE_MANUSCRIPT = {
    "explain": lambda root: ("explain", str(root / "manuscript" / "main.md")),
    "render": lambda root: ("render", str(root)),
    "bind": lambda root: ("bind", str(root)),
    "bind --apply": lambda root: ("bind", str(root), "--apply"),
    "methods": lambda root: ("methods", str(root)),
    "sync-bib": lambda root: ("sync-bib", str(root)),
    "build --skip-checks": lambda root: ("build", str(root), "--offline", "--skip-checks"),
    "submit --skip-checks": lambda root: ("submit", str(root), "--offline", "--skip-checks"),
}


@pytest.mark.parametrize("command", list(READS_THE_MANUSCRIPT))
def test_a_command_says_in_a_sentence_which_manuscript_file_is_not_utf8(
    command: str, project: Path, capsys
) -> None:
    """Exit 2 and one sentence that names the file and the line, as for any other error the
    tool raises on purpose."""
    source = project / "manuscript" / "main.md"
    line = in_a_code_page(source)
    before = source.read_bytes()

    assert run(*READS_THE_MANUSCRIPT[command](project)) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert (
        f"manuscript-guard: {source}: cannot read as UTF-8: the byte 0xe9 on line {line} "
        "is not UTF-8. Save the file as UTF-8."
    ) in captured.err
    assert source.read_bytes() == before, "and the file is left as it was found"
    assert not list((project / "build").glob("*.docx")), "nothing was built from it"


def test_explain_reads_a_file_that_is_utf8_as_before(project: Path, capsys) -> None:
    """The lines `explain` prints are counted in the text as it was always read: a file with
    Windows line endings and an accented letter gives the same rows as the file it came from."""
    source = project / "manuscript" / "main.md"
    assert run("explain", str(source)) == 0
    expected = capsys.readouterr().out

    windows = source.read_text(encoding="utf-8").replace("\n", "\r\n") + "\r\nCafé society.\r\n"
    source.write_bytes(windows.encode("utf-8"))
    assert run("explain", str(source)) == 0
    assert capsys.readouterr().out == expected


#: What `explain` and `bind` build the classifier from, left so that it cannot be built, the
#: error each command ended in a traceback with, and what `check` says of the key.
NO_CLASSIFIER = {
    "terms: 5": ("terms", 5, "terms: 5 is not of type 'array'"),
    "a pattern that does not compile": (
        "conventions",
        [{"pattern": "[0-9", "why": "a count"}],
        "conventions/0/pattern: '[0-9' is not a regular expression",
    ),
}


@pytest.mark.parametrize("case", list(NO_CLASSIFIER))
def test_explain_and_bind_run_where_a_setting_cannot_be_used(
    case: str, project: Path, capsys
) -> None:
    """`TypeError: 'int' object is not iterable` and `re.error`. The key is not read, both
    commands run, and `check` says what is wrong with it."""
    import yaml

    key, value, said = NO_CLASSIFIER[case]
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document[key] = value
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    assert run("explain", str(project / "manuscript" / "main.md")) == 0
    assert run("bind", str(project)) in (0, 1)
    assert "Traceback" not in capsys.readouterr().err
    assert run("check", str(project)) == 1
    assert said in capsys.readouterr().out


def test_check_reports_a_manuscript_file_that_is_not_utf8_as_one_finding(
    project: Path, capsys
) -> None:
    """Exit 1 and a report, since the gates that do not read the manuscript still ran. It was
    seven findings, one for each gate that read the file, and none of them named it."""
    line = in_a_code_page(project / "manuscript" / "main.md")

    assert run("check", str(project)) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    where = Path("manuscript") / "main.md"
    assert f"[FAIL] G0 {where}:{line}\n" in captured.out
    assert (
        f"manuscript/main.md: cannot read as UTF-8: the byte 0xe9 on line {line} is not UTF-8. "
        "Save the file as UTF-8."
    ) in captured.out
    assert "could not run" not in captured.out
    assert "bug" not in captured.out
    assert "\n1 failing, " in captured.out


def test_check_json_carries_the_file_and_the_line(project: Path, capsys) -> None:
    source = project / "manuscript" / "main.md"
    line = in_a_code_page(source)

    assert run("check", str(project), "--json") == 1
    document = json.loads(capsys.readouterr().out)
    failing = [f for f in document["findings"] if f["severity"] == "fail"]
    assert [(f["code"], f["path"], f["line"]) for f in failing] == [
        ("manuscript-unreadable", str(source), line)
    ]


def test_build_refuses_a_manuscript_file_that_is_not_utf8(project: Path, capsys) -> None:
    """The build runs the same gates first, and stops on the same finding."""
    in_a_code_page(project / "manuscript" / "main.md")

    assert run("build", str(project), "--offline") == 1
    captured = capsys.readouterr()
    assert "manuscript/main.md: cannot read as UTF-8: the byte 0xe9" in captured.out
    assert "could not run" not in captured.out
    assert not list((project / "build").glob("*.docx"))


def test_review_holds_to_the_rounds_asked_for_beside_a_key_the_schema_refuses(
    project: Path, capsys
) -> None:
    """`review` does not print the schema's findings, so what it reads of `review:` is its
    whole answer. Five rounds asked for, two complete, and one mistyped key beside it."""
    paper = project / "paper.yaml"
    paper.write_text(
        paper.read_text(encoding="utf-8") + "\nreview:\n  rounds_required: 5\n  typo: 1\n",
        encoding="utf-8",
    )

    assert run("review", str(project), "--submission") == 1
    assert "2 of 5 review round(s) complete" in capsys.readouterr().out


def test_check_submission_is_stricter_than_a_draft(project: Path) -> None:
    shutil.rmtree(project / "review")
    assert run("check", str(project)) == 0
    assert run("check", str(project), "--submission") == 1


# ---------------------------------------------------------------- submit


@needs_pandoc
def test_submit_refuses_while_the_submission_check_fails(project: Path, capsys) -> None:
    """The guarantee in submission.py's own docstring, and it was untested.

    A mutation that replaced this guard with `if False` left all 376 other tests passing.
    """
    shutil.rmtree(project / "review")
    assert run("submit", str(project), "--offline") == 1
    assert "not assembled" in capsys.readouterr().out
    assert not (project / "build" / "submission").exists()


@needs_pandoc
def test_submit_assembles_once_the_check_passes(project: Path, capsys) -> None:
    assert run("submit", str(project), "--offline") == 0
    pack = project / "build" / "submission"
    assert (pack / "MANIFEST.yaml").exists()
    assert (pack / "title-page.md").exists()
    assert "covering letter" in capsys.readouterr().out


@needs_pandoc
def test_submit_can_be_overridden_deliberately(project: Path) -> None:
    shutil.rmtree(project / "review")
    assert run("submit", str(project), "--offline", "--skip-checks") == 0
    assert (project / "build" / "submission" / "MANIFEST.yaml").exists()


# ---------------------------------------------------------------- build


@needs_pandoc
def test_build_refuses_while_a_gate_fails(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n99999 loose.\n", encoding="utf-8")
    assert run("build", str(project), "--offline") == 1


#: What `paper.yaml` can say that the front matter of the build must carry as text: a
#: double quotation mark, a backslash, TeX. Each was written between double quotation marks
#: into YAML by hand, so `"` ended the string and the build stopped, and `\a` became the
#: control character 7, which made a .docx Word refuses to open. A word that survives
#: pandoc's reading of each as Markdown, as it reads the text.
FRONT_MATTER = {
    "a keyword with quotation marks": ("keywords", 'say "hi" there', "hi"),
    "a keyword with TeX in it": ("keywords", r"$\alpha$-synuclein", "synuclein"),
    "a keyword with a backslash": ("keywords", r"5\% of TNF signalling", "signalling"),
    "a list of keywords with TeX in it": ("keywords", [r"$\alpha$-synuclein", "signal"], "signal"),
    "a title with both": ("title", r'The "weekend effect" in TNF$\alpha$ signalling', "weekend"),
    "a short title with both": ("short_title", r'"Weekend" and TNF$\alpha$', "Weekend"),
}
# Three of these rows held `TNF\alpha` outside dollar signs until that became a finding and
# a refusal of the build's (`TEX_OUTSIDE` below): the document was readable, and printed
# without the `\alpha`.


@needs_pandoc
@pytest.mark.parametrize("case", list(FRONT_MATTER))
def test_the_front_matter_carries_quotes_and_backslashes_into_a_readable_document(
    case: str, project: Path
) -> None:
    """A list of keywords, a title and a short title the schema accepts went through `check`
    and a checked build with the document unreadable: a false pass. One keyword typed
    without a dash took the same road in an unchecked build. The document must be one Word
    can open: its XML parses."""
    import xml.etree.ElementTree as ET
    import zipfile

    import yaml

    key, value, survives = FRONT_MATTER[case]
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document[key] = value
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    assert run("build", str(project), "--offline", "--skip-checks") == 0
    built = next((project / "build").glob("manuscript*.docx"))
    with zipfile.ZipFile(built) as docx:
        for member in ("docProps/core.xml", "word/document.xml"):
            ET.fromstring(docx.read(member))  # raises on a control character
        properties = docx.read("docProps/core.xml").decode("utf-8")
        body = docx.read("word/document.xml").decode("utf-8")
    assert survives in (properties if key == "keywords" else body)


#: A title or a keyword written between double quotation marks in `paper.yaml`, where YAML
#: reads a backslash as an escape: `\a` is the control character U+0007. Written into the
#: document's properties, it made a .docx Word refuses to open, and `check` and a checked
#: build both passed it. What replaces which lines of the example's `paper.yaml`, and the
#: place `check` names.
YAML_ESCAPES = {
    "a title": (
        'title: "Reporting of hepatic injury',
        'title: "Effects of \\alpha-blockers on hepatic injury"\n'
        'old_title: "Reporting of hepatic injury',
        "title",
        "U+0007",
    ),
    "a keyword": (
        "  - pharmacovigilance\n",
        '  - "$\\alpha$-synuclein"\n',
        "keywords/0",
        "U+0007",
    ),
    # `\v` is U+000B, which a line split took for the end of a line: folded into a
    # space, the letter after it was lost and nothing was refused.
    "a title with \\varepsilon": (
        'title: "Reporting of hepatic injury',
        'title: "The $\\varepsilon$ coefficient"\n'
        'old_title: "Reporting of hepatic injury',
        "title",
        "U+000B",
    ),
}


@pytest.mark.parametrize("case", list(YAML_ESCAPES))
def test_a_control_character_from_a_yaml_escape_is_refused_by_check_and_the_build(
    case: str, project: Path, capsys
) -> None:
    old, new, where, character = YAML_ESCAPES[case]
    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    assert text.count(old) == 1
    text = text.replace(old, new, 1)
    if new.startswith("title"):  # the old title moved under a name YAML ignores: drop it
        text = "\n".join(line for line in text.splitlines() if not line.startswith("old_title"))
    paper.write_text(text + "\n", encoding="utf-8")

    assert run("check", str(project)) == 1
    assert f"{where}: holds the control character {character}" in capsys.readouterr().out

    assert run("build", str(project), "--offline", "--skip-checks") == 2
    said = capsys.readouterr().err
    assert "paper.yaml" in said
    assert character in said
    assert "Traceback" not in said
    assert not list((project / "build").glob("*.docx"))


#: An escape in `paper.yaml` that makes something no document can carry and that is not a
#: control character. `check` passed each. The build stopped on the first in pandoc's words
#: about `build/manuscript.md`, and ended in a traceback on the second (`UnicodeEncodeError`).
NO_CHARACTER = {
    "a non-character": ('title: "A\\uFFFFstudy"', "the non-character U+FFFF"),
    "a pair written as JSON writes it": (
        'title: "\\ud83d\\ude00 smile"',
        "the surrogate U+D83D",
    ),
}


@pytest.mark.parametrize("case", list(NO_CHARACTER))
def test_an_escape_that_makes_no_character_is_refused_by_check_and_the_build(
    case: str, project: Path, capsys
) -> None:
    written, called = NO_CHARACTER[case]
    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    paper.write_text(text.replace(old, written, 1), encoding="utf-8")

    assert run("check", str(project)) == 1
    assert f"title: holds {called}, which no document can carry" in capsys.readouterr().out

    assert run("build", str(project), "--offline", "--skip-checks") == 2
    said = capsys.readouterr().err
    assert "paper.yaml" in said
    assert called in said
    assert "Traceback" not in said
    assert not list((project / "build").glob("*.docx"))


def test_an_escape_that_takes_a_letter_is_refused_by_check_and_the_build(
    project: Path, capsys
) -> None:
    """`"The $\\nu$ frequency"`: YAML reads the escape as the end of a line, the build
    folds it into a space, and the title was printed `The $ u$ frequency`, through `check`
    and a checked build. The finding names the key and the escape, and the build refuses
    it as well where the check is skipped."""
    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    paper.write_text(text.replace(old, 'title: "The $\\nu$ frequency"', 1), encoding="utf-8")

    assert run("check", str(project)) == 1
    assert "title: `\\nu` between double quotation marks" in capsys.readouterr().out

    assert run("build", str(project), "--offline", "--skip-checks") == 2
    said = capsys.readouterr().err
    assert "paper.yaml" in said
    assert "`\\nu` between double quotation marks" in said
    assert "where a line break or a tab was meant, write a space" in said
    assert "Traceback" not in said
    assert not list((project / "build").glob("*.docx"))


@needs_pandoc
@pytest.mark.parametrize(
    "written",
    ["title: 'The $\\nu$ frequency'", "title: The $\\nu$ frequency"],
    ids=["single quotation marks", "no quotation marks"],
)
def test_the_same_title_where_a_backslash_is_a_backslash_builds_with_its_letter(
    written: str, project: Path
) -> None:
    import re
    import zipfile

    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    paper.write_text(text.replace(old, written, 1), encoding="utf-8")

    assert run("check", str(project)) == 0
    assert run("build", str(project), "--offline") == 0
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as docx:
        properties = docx.read("docProps/core.xml").decode("utf-8")
    title = re.search("<dc:title>(.*?)</dc:title>", properties, re.S)
    assert title is not None
    assert title[1] == "The \\nu frequency"


@needs_pandoc
def test_import_takes_back_a_document_built_before_the_lost_letter_was_refused(
    project: Path, monkeypatch, capsys
) -> None:
    """`import` rebuilds the source to compare the returned document with. A refusal newer
    than the document is not import's to enforce: it blocked the return of a document a
    co-author was holding, built when the title was printed with a space for the break."""
    from manuscript_guard.build import document
    from manuscript_guard.contracts import project as contract

    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    paper.write_text(
        text.replace(old, 'title: "First part:\\nsecond part"', 1), encoding="utf-8"
    )

    with monkeypatch.context() as before:  # as the tool was before the refusal
        before.setattr(document, "lost_letters", lambda path: [])
        before.setattr(contract, "lost_letters", lambda path: [])
        assert run("build", str(project), "--offline") == 0
    sent = project / "build" / "manuscript.docx"
    capsys.readouterr()

    assert run("import", str(sent), str(project)) == 0
    assert "nothing came back" in capsys.readouterr().out


#: TeX outside dollar signs in what the build prints of `paper.yaml`: what replaces which
#: line of the example's, the place `check` names and the command it names there. Pandoc
#: reads each value as Markdown and the Word writer keeps TeX only as maths, so each passed
#: `check` and a checked build and was printed without the command, and without the number
#: after it where there is one.
TEX_OUTSIDE = {
    "a title": (
        "title: ",
        "title: 'IFN-" + chr(92) + "gamma release assays in hepatic injury'",
        "title",
        chr(92) + "gamma",
    ),
    "a short title with a number after the command": (
        "short_title: ",
        "short_title: 'Injury at 12 " + chr(92) + "pm 3 months'",
        "short_title",
        chr(92) + "pm",
    ),
    "a keyword": (
        "  - pharmacovigilance",
        "  - TNF" + chr(92) + "alpha signalling",
        "keywords/0",
        chr(92) + "alpha",
    ),
}


def _with_line(project: Path, starts: str, written: str) -> None:
    """The example's `paper.yaml` with the one line that starts with `starts` replaced."""
    paper = project / "paper.yaml"
    lines = paper.read_text(encoding="utf-8").split(chr(10))
    (at,) = [index for index, line in enumerate(lines) if line.startswith(starts)]
    lines[at] = written
    paper.write_text(chr(10).join(lines), encoding="utf-8")


@pytest.mark.parametrize("stage", ["design", "drafting", "submission"])
@pytest.mark.parametrize("case", list(TEX_OUTSIDE))
def test_tex_outside_dollar_signs_is_refused_by_check_at_every_stage_and_by_the_build(
    case: str, stage: str, project: Path, capsys
) -> None:
    starts, written, where, command = TEX_OUTSIDE[case]
    _with_line(project, starts, written)
    paper = project / "paper.yaml"
    paper.write_text(
        paper.read_text(encoding="utf-8") + chr(10) + f"stage: {stage}" + chr(10),
        encoding="utf-8",
    )
    # A keyword is printed in the document's properties only, where maths is written as
    # its TeX, so there the remedy is the character itself.
    remedy = (
        "write it as text and not as maths"
        if where.startswith("keywords")
        else f"if it is maths, write `${command}$`"
    )
    says = (
        f"`{command}` stands outside dollar signs, and the document is printed without it; "
        f"{remedy}"
    )

    assert run("check", str(project)) == 1
    assert f"{where}: {says}" in capsys.readouterr().out

    assert run("build", str(project), "--offline", "--skip-checks") == 2
    said = capsys.readouterr().err
    assert "paper.yaml" in said
    assert f"`{where.split('/')[0]}`: {says}" in said
    assert "between dollar signs" in said
    assert "Traceback" not in said
    assert not list((project / "build").glob("*.docx"))


@needs_pandoc
def test_the_same_title_with_its_tex_between_dollar_signs_builds_with_the_letter(
    project: Path,
) -> None:
    import zipfile

    _with_line(project, "title: ", "title: 'IFN-$" + chr(92) + "gamma$ release assays'")

    assert run("check", str(project)) == 0
    assert run("build", str(project), "--offline") == 0
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as docx:
        body = docx.read("word/document.xml").decode("utf-8")
    assert chr(0x3B3) in body, "the gamma, as the maths Word shows"


@needs_pandoc
def test_a_keyword_with_maths_is_printed_as_its_tex_and_one_with_the_character_as_typed(
    project: Path,
) -> None:
    """Why the finding tells a keyword to hold the character: a keyword is printed in the
    document's properties only, and pandoc writes maths there as its TeX."""
    import re
    import zipfile

    alpha = chr(0x3B1)
    _with_line(project, "  - pharmacovigilance", "  - TNF$" + chr(92) + "alpha$ signalling")
    _with_line(project, "  - disproportionality", "  - TNF" + alpha + " inhibitors")

    assert run("check", str(project)) == 0
    assert run("build", str(project), "--offline") == 0
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as docx:
        properties = docx.read("docProps/core.xml").decode("utf-8")
        body = docx.read("word/document.xml").decode("utf-8")
    keywords = re.search("<cp:keywords>(.*?)</cp:keywords>", properties, re.S)
    assert keywords is not None
    assert keywords[1].split(", ")[:2] == [
        "TNF" + chr(92) + "alpha signalling",
        "TNF" + alpha + " inhibitors",
    ]
    assert "signalling" not in body, "the text of the document prints no keyword"


@needs_pandoc
def test_import_takes_back_a_document_built_before_tex_outside_dollar_signs_was_refused(
    project: Path, monkeypatch, capsys
) -> None:
    """As for a lost letter: `import` builds the source again to compare the returned
    document with, and a refusal newer than the document is not import's to enforce. The
    title was printed without its `\\gamma` when the document went out, and builds so again."""
    from manuscript_guard.build import document
    from manuscript_guard.contracts import project as contract

    _with_line(project, "title: ", "title: 'IFN-" + chr(92) + "gamma release assays'")

    with monkeypatch.context() as before:  # as the tool was before the refusal
        before.setattr(document, "outside_maths", lambda text, **how: None)
        before.setattr(contract, "outside_maths", lambda text, **how: None)
        assert run("build", str(project), "--offline") == 0
    sent = project / "build" / "manuscript.docx"
    capsys.readouterr()

    assert run("build", str(project), "--offline", "--skip-checks") == 2, "refused now"
    capsys.readouterr()
    assert sent.is_file(), "and the document that went out is still there"

    assert run("import", str(sent), str(project)) == 0
    assert "nothing came back" in capsys.readouterr().out


@needs_pandoc
def test_a_block_title_is_printed_without_a_space_after_it(project: Path) -> None:
    """A block ends with a line break, and folded into a space it stood after `al.`: pandoc
    reads a space there as a no-break space, and the title was printed with one after it.
    A keyword written as a block got one before the comma."""
    import zipfile

    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    text = text.replace(old, "title: |" + chr(10) + "  Outcomes reported by Smith et al.", 1)
    assert text.count("  - pharmacovigilance" + chr(10)) == 1
    text = text.replace(
        "  - pharmacovigilance" + chr(10), "  - |" + chr(10) + "    drug A vs." + chr(10), 1
    )
    paper.write_text(text, encoding="utf-8")

    assert run("build", str(project), "--offline", "--skip-checks") == 0
    built = next((project / "build").glob("manuscript*.docx"))
    with zipfile.ZipFile(built) as docx:
        properties = docx.read("docProps/core.xml").decode("utf-8")
    assert chr(0xA0) not in properties
    assert "<dc:title>Outcomes reported by Smith et al.</dc:title>" in properties
    assert "<cp:keywords>drug A vs., disproportionality, hepatotoxicity</cp:keywords>" in properties


@needs_pandoc
def test_a_title_with_a_blank_line_in_it_is_printed_on_one_line(project: Path) -> None:
    """Pandoc read a title holding a blank line as two paragraphs, and the Word writer left
    the title out of the document. Written by hand between quotation marks, YAML had folded
    the lines into one, which is what the document gets."""
    import re
    import zipfile

    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    old = next(line for line in text.splitlines() if line.startswith("title: "))
    paper.write_text(
        text.replace(old, "title: |\n  First part\n\n  second part", 1), encoding="utf-8"
    )

    assert run("build", str(project), "--offline", "--skip-checks") == 0
    built = next((project / "build").glob("manuscript*.docx"))
    with zipfile.ZipFile(built) as docx:
        properties = docx.read("docProps/core.xml").decode("utf-8")
        body = docx.read("word/document.xml").decode("utf-8")
    assert "<dc:title>First part second part</dc:title>" in properties
    title = re.search(r'<w:pStyle w:val="Title"\s*/>.*?</w:p>', body, re.S)
    assert title is not None, "no paragraph in the document carries the title"
    assert "First part second part" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", title[0]))


@needs_pandoc
@pytest.mark.parametrize("word", ["pharmacovigilance", "R"])
def test_an_unchecked_build_prints_one_keyword_typed_without_a_dash_whole(
    word: str, project: Path
) -> None:
    """`keywords: pharmacovigilance`, one word where a list is expected, which the schema
    refuses. A build that was asked not to check prints what was typed, and this word is
    the one keyword: it was printed letter by letter, then not at all."""
    import zipfile

    import yaml

    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["keywords"] = word
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    assert run("build", str(project), "--offline", "--skip-checks") == 0
    with zipfile.ZipFile(project / "build" / "manuscript.UNCHECKED.docx") as docx:
        properties = docx.read("docProps/core.xml").decode("utf-8")
    assert f"<cp:keywords>{word}</cp:keywords>" in properties


@needs_pandoc
def test_build_skip_checks_builds_under_a_name_that_says_so(project: Path, capsys) -> None:
    """An unchecked build must not be able to pass for a checked one.

    Left as `manuscript.docx` it is the file a co-author opens and a journal receives —
    and reverting the source afterwards makes `check` pass while the stale document still
    holds the wrong number, with nothing on disk recording which one was skipped.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n99999 loose.\n", encoding="utf-8")
    assert run("build", str(project), "--offline", "--skip-checks") == 0
    assert (project / "build" / "manuscript.UNCHECKED.docx").exists()
    assert not (project / "build" / "manuscript.docx").exists()
    assert "UNCHECKED" in capsys.readouterr().out


@needs_pandoc
def test_a_clean_build_keeps_the_plain_name(project: Path) -> None:
    assert run("build", str(project), "--offline") == 0
    assert (project / "build" / "manuscript.docx").exists()


@needs_pandoc
def test_a_rerun_analysis_makes_the_built_document_stale(project: Path) -> None:
    """The commoner way a build goes stale, and the first version could not see it.

    The stamp compared `manuscript_digest`, which covers `manuscript/*.md` — so re-running
    the analysis on new data with the prose untouched left the digest identical while the
    .docx still showed the old number. An adversarial review walked an ROR from 3.84 to
    28.80 with `check --submission` reporting nothing at all.
    """
    assert run("build", str(project), "--offline") == 0
    assert run("check", str(project), "--stage", "internal-review") == 0

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["value"] = 28.80
    document["values"]["ror.point"]["display"] = "28.80"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    # Asserted by code rather than by exit status, and the test stops here: changing a
    # result legitimately unsettles the figure and its review as well, so a bare exit code
    # would not show which check fired, and rebuilding is blocked by those other findings.
    # What is under test is that the prose never moved and the document went stale anyway.
    assert "document-stale" in {f.code for f in _findings(project)}


def _findings(project: Path):
    from manuscript_guard.cli import _run_gates

    report, _p, _s, _d = _run_gates(project, stage="internal-review")
    return report.findings


@needs_pandoc
def test_a_document_with_no_stamp_is_reported_rather_than_skipped(project: Path) -> None:
    """A missing stamp was a `continue`, so deleting one file disabled the check."""
    from manuscript_guard.build.document import SOURCE_STAMP

    assert run("build", str(project), "--offline") == 0
    (project / "build" / f"manuscript.docx{SOURCE_STAMP}").unlink()

    assert run("check", str(project), "--stage", "internal-review") == 0
    out = capsys_text(project)
    assert "no record of the source" in out


def capsys_text(project: Path) -> str:
    from manuscript_guard.cli import _run_gates

    report, _p, _s, _d = _run_gates(project, stage="internal-review")
    return report.render(project)


@needs_pandoc
def test_a_built_document_that_no_longer_matches_its_source_is_reported(project: Path) -> None:
    """Nothing linked the .docx to the manuscript it came from.

    So editing the source and forgetting to rebuild left every gate green over a document
    still holding the old number — and that document is the file a co-author opens and a
    journal receives. Not due until internal review, because a stale build while drafting
    is normal: you rebuild when you need it.
    """
    assert run("build", str(project), "--offline") == 0
    assert run("check", str(project), "--stage", "internal-review") == 0

    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later thought.\n", encoding="utf-8")

    assert run("check", str(project), "--stage", "drafting") == 0, "not due yet while drafting"
    assert run("check", str(project), "--stage", "internal-review") == 1
    assert run("build", str(project), "--offline") == 0
    assert run("check", str(project), "--stage", "internal-review") == 0


@needs_pandoc
def test_an_overridden_submission_pack_records_that_in_its_manifest(project: Path) -> None:
    """The pack was byte-indistinguishable from one that passed. Six months later nobody
    can tell, and the manifest's whole purpose is to be the thing you can tell from."""
    shutil.rmtree(project / "review")
    assert run("submit", str(project), "--offline", "--skip-checks") == 0
    manifest = (project / "build" / "submission" / "MANIFEST.yaml").read_text(encoding="utf-8")
    assert "SKIPPED" in manifest


@needs_pandoc
def test_a_checked_submission_pack_says_so(project: Path) -> None:
    assert run("submit", str(project), "--offline") == 0
    manifest = (project / "build" / "submission" / "MANIFEST.yaml").read_text(encoding="utf-8")
    assert "checks: passed" in manifest


# ---------------------------------------------------------------- supplementary material


@needs_pandoc
def test_the_supplement_is_its_own_document(project: Path) -> None:
    """Welded into the manuscript it counted against the journal's word limit, arrived as
    pages an editor had to find the end of, and could not be uploaded to the supplementary
    slot every submission system has."""
    from manuscript_guard.text.docx import read_docx

    assert run("build", str(project), "--offline") == 0
    supplement = project / "build" / "supplementary.docx"
    assert supplement.exists(), "the example's supplement did not build"
    assert "Table S1" in read_docx(supplement)
    assert "Code lists used to identify" not in read_docx(project / "build" / "manuscript.docx")


@needs_pandoc
def test_the_supplement_carries_its_own_title(project: Path) -> None:
    """A supplement under the paper's own title and running head reads, in a journal's
    submission system, as a second copy of the paper."""
    from manuscript_guard.text.docx import read_docx

    assert run("build", str(project), "--offline") == 0
    assert "Supplementary material for" in read_docx(project / "build" / "supplementary.docx")


@needs_pandoc
def test_a_project_with_no_supplement_builds_one_document(project: Path, capsys) -> None:
    """The supplement is built alongside the paper when there is one, and not mentioned
    when there is not."""
    import shutil

    # The table the supplement placed has to go back into the paper, or it is emitted and
    # unplaced and the build refuses - which is the coverage check doing its job.
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "\nThe reporting odds ratio was computed",
            "\n{{table.outcome_codes}}\n\nThe reporting odds ratio was computed",
        ),
        encoding="utf-8",
    )
    shutil.rmtree(project / "manuscript" / "supplementary")

    assert run("build", str(project), "--offline", "--skip-checks") == 0
    assert not (project / "build" / "supplementary.docx").exists()
    assert "supplementary" not in capsys.readouterr().out


@needs_pandoc
def test_the_supplement_reaches_the_submission_pack(project: Path) -> None:
    assert run("submit", str(project), "--offline") == 0
    pack = project / "build" / "submission"
    assert (pack / "supplementary.docx").exists()
    assert "supplementary.docx" in (pack / "MANIFEST.yaml").read_text(encoding="utf-8")


def test_the_supplement_does_not_count_against_the_word_limit(project: Path) -> None:
    """The concrete harm of having no supplementary concept: a compliant paper reported as
    over-length, with the author's recourse being to cut material the journal never counts.
    """
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates import check_journal

    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    before = check_journal(load_project(project)[0]).counts["main_text_words"]
    supplement.write_text(
        supplement.read_text(encoding="utf-8") + "\n\n" + ("filler words here. " * 400),
        encoding="utf-8",
    )
    after = check_journal(load_project(project)[0]).counts["main_text_words"]
    assert before == after, "1200 supplementary words moved the main-text count"


def test_the_supplement_is_still_checked_like_the_paper(project: Path) -> None:
    """Not counted is not unread. A fabricated number in a supplementary table is still
    fabricated, and a supplement nobody checks is the obvious place to put one."""
    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    supplement.write_text(
        supplement.read_text(encoding="utf-8") + "\n\nThe rate was 9.99 per thousand.\n",
        encoding="utf-8",
    )
    assert run("check", str(project)) == 1


# ---------------------------------------------------------------- audit


def test_audit_is_advisory_by_default(project: Path, capsys) -> None:
    paper = project / "loose.md"
    paper.write_text("The ratio was 9.99.\n", encoding="utf-8")
    assert run("audit", str(paper), "--against", str(project / "results")) == 0
    assert "9.99" in capsys.readouterr().out


def test_audit_strict_exits_one_on_an_unmatched_number(project: Path) -> None:
    paper = project / "loose.md"
    paper.write_text("The ratio was 9.99.\n", encoding="utf-8")
    assert run("audit", str(paper), "--against", str(project / "results"), "--strict") == 1


def test_audit_strict_exits_zero_when_everything_matches(project: Path) -> None:
    paper = project / "loose.md"
    paper.write_text("Hepatic injury was reported in 77 cases.\n", encoding="utf-8")
    assert run("audit", str(paper), "--against", str(project / "results"), "--strict") == 0


def test_audit_with_nothing_to_read_exits_two(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run("audit", str(empty), "--against", str(tmp_path)) == 2
    assert "nothing to audit" in capsys.readouterr().err


def test_audit_against_a_path_that_does_not_exist_exits_two(project: Path, capsys) -> None:
    """A typo in --against gave "0 distinct numbers from 0 output file(s)", every number in
    the paper reported missing, and exit 0."""
    paper = project / "loose.md"
    paper.write_text("Hepatic injury was reported in 77 cases.\n", encoding="utf-8")
    typo = project / "resluts"
    assert run("audit", str(paper), "--against", str(project / "results"), str(typo)) == 2
    assert "resluts" in capsys.readouterr().err


def test_audit_of_a_paper_that_does_not_exist_exits_two(project: Path, capsys) -> None:
    paper = project / "loose.md"
    paper.write_text("Hepatic injury was reported in 77 cases.\n", encoding="utf-8")
    missing = project / "supplement.md"
    assert run("audit", str(paper), str(missing), "--against", str(project / "results")) == 2
    assert "supplement.md" in capsys.readouterr().err


def test_audit_against_nothing_it_can_read_exits_two(project: Path, capsys) -> None:
    paper = project / "loose.md"
    paper.write_text("Hepatic injury was reported in 77 cases.\n", encoding="utf-8")
    sheet = project / "results.xlsx"
    sheet.write_bytes(b"PK\x03\x04")
    assert run("audit", str(paper), "--against", str(sheet)) == 2
    assert "results.xlsx" in capsys.readouterr().err


def test_audit_help_names_every_format_it_reads(capsys) -> None:
    from manuscript_guard.audit import BACKING_SUFFIXES

    with pytest.raises(SystemExit):
        run("audit", "--help")
    helptext = " ".join(capsys.readouterr().out.split())
    assert all(suffix in helptext for suffix in BACKING_SUFFIXES), helptext


# ---------------------------------------------------------------- the rest


def test_stages_lists_every_stage(capsys) -> None:
    assert run("stages") == 0
    out = capsys.readouterr().out
    for stage in ("design", "analysis", "drafting", "internal-review", "submission"):
        assert stage in out
    assert "fails at every stage" in out


def test_explain_agrees_with_check(project: Path, capsys) -> None:
    """The debugging command was giving a different answer from the gate it explains.

    `explain` classified with no section, so every `methods_only` rule fired everywhere: a
    fabricated `p < 0.001` in the Results was reported as a recognised convention while
    `check` failed it. That answer is the input to deciding whether to add a `conventions:`
    exemption — the one mechanism that makes G2 vacuous — so being wrong here is worse than
    being silent.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(
        # 0.01, not the example's own alpha: typed, that one is a declared parameter.
        "# Methods\n\nSignificance was set at p < 0.01.\n\n"
        "# Results\n\nThe excess was significant (p < 0.001).\n",
        encoding="utf-8",
    )
    assert run("explain", str(path)) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    methods = next(line for line in lines if " 0.01 " in f" {line} ")
    results = next(line for line in lines if " 0.001 " in f" {line} ")
    assert methods.startswith("ok"), "a threshold in Methods is a convention"
    assert results.startswith("FAIL"), "the same characters in Results are a finding"

    assert run("check", str(project)) == 1


def test_explain_shows_the_rule_behind_each_number(project: Path, capsys) -> None:
    assert run("explain", str(project / "manuscript" / "main.md")) == 0
    out = capsys.readouterr().out
    assert "convention" in out
    assert "rate-denominator" in out or "confidence-level" in out


def test_methods_reports_and_reconciles(project: Path, capsys) -> None:
    assert run("methods", str(project)) == 0
    (project / "analysis" / "01_disproportionality.py").write_text("# changed\n", encoding="utf-8")
    assert run("methods", str(project)) == 1
    assert run("methods", str(project), "--reconcile") == 0
    assert run("methods", str(project)) == 0


def test_review_prints_the_digest_a_record_must_carry(project: Path, capsys) -> None:
    assert run("review", str(project), "--digest") == 0
    digest = capsys.readouterr().out.strip()
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_review_files_prints_a_paste_ready_block(project: Path, capsys) -> None:
    """A reviewer who has to assemble this by hand will omit it instead."""
    import yaml

    assert run("review", str(project), "--files") == 0
    block = yaml.safe_load(capsys.readouterr().out)
    assert set(block) == {"file_sha256"}
    # The supplement too: a reviewer's finding list describes what they read, and they read
    # the supplement. Its absence here is what lets it change under a review that still says
    # it covers the manuscript.
    assert set(block["file_sha256"]) == {"main.md", "supplementary/S1_code_lists.md"}
    assert all(len(v) == 64 for v in block["file_sha256"].values())


def test_checklist_scaffolds_and_is_idempotent(project: Path, capsys) -> None:
    assert run("checklist", "DEMO-OBS", "--path", str(project)) == 0
    assert "all already present" in capsys.readouterr().out


# ------------------------------------------------------------------ a console that is not UTF-8


@pytest.mark.parametrize("encoding", ["cp437", "cp850", "cp1252"])
def test_output_survives_a_console_that_is_not_utf8(encoding: str, monkeypatch) -> None:
    """A Windows console is whatever code page it started with, and each rejects a different
    subset: cp437 and cp850 have no em dash, cp1252 has one but no `\u2265`. Printing raised
    UnicodeEncodeError from inside the gate run, so `check` exited 2 - "the check could not
    be run at all" - on a manuscript that was merely failing a gate.
    """
    import io

    from manuscript_guard.cli import _survive_the_console

    line = "an em dash \u2014 a ratio \u2265 1.0 an ellipsis\u2026"

    raw = io.TextIOWrapper(io.BytesIO(), encoding=encoding, newline="")
    with pytest.raises(UnicodeEncodeError):
        raw.write(line)  # the bug, still reachable without the shim

    buffer = io.TextIOWrapper(io.BytesIO(), encoding=encoding, newline="")
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(sys, "stderr", buffer)
    _survive_the_console()

    print(line)
    buffer.flush()
    written = buffer.buffer.getvalue().decode(encoding)
    assert "--" in written and ">=" in written and "..." in written
    assert "?" not in written, "folded, not blanked: `--` still reads as English"


def test_a_utf8_console_keeps_the_typography(monkeypatch) -> None:
    """The fold is a fallback, not a downgrade applied to everyone."""
    import io

    from manuscript_guard.cli import _survive_the_console

    buffer = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(sys, "stderr", buffer)
    _survive_the_console()

    print("an em dash \u2014 here")
    buffer.flush()
    assert "\u2014" in buffer.buffer.getvalue().decode("utf-8")


def test_json_output_is_ascii_so_a_pipe_cannot_truncate_it(project: Path, capsys) -> None:
    assert run("check", str(project), "--json") in (0, 1)
    out = capsys.readouterr().out
    out.encode("ascii")  # would raise if a literal em dash survived
    assert json.loads(out)["counts"]


def test_check_does_not_report_exit_2_for_a_failing_gate(project: Path, capsys) -> None:
    """Exit 2 means the check could not run. A gate failure is exit 1 and nothing else."""
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nThe rate was 47 per 1000.\n",
                    encoding="utf-8")
    assert run("check", str(project)) == 1


def test_audit_of_nothing_readable_exits_two(project: Path, capsys) -> None:
    """An unreadable paper printed "Audited 0 file(s) … 0 not found" and exited 0, even
    with --strict: a clean-looking report of nothing."""
    locked = project / "locked.docx"
    locked.write_bytes(b"not a zip")
    assert run("audit", str(locked), "--against", str(project / "results"), "--strict") == 2
    assert "locked.docx" in capsys.readouterr().err


def test_audit_strict_fails_when_a_paper_could_not_be_read(project: Path) -> None:
    readable = project / "loose.md"
    readable.write_text("Hepatic injury was reported in 77 cases.\n", encoding="utf-8")
    locked = project / "locked.docx"
    locked.write_bytes(b"not a zip")
    args = ("audit", str(readable), str(locked), "--against", str(project / "results"))
    assert run(*args) == 0
    assert run(*args, "--strict") == 1


# ---------------------------------------------------------------- the parser


def _commands() -> dict[str, argparse.ArgumentParser]:
    """The parser of every command, by the command's name."""
    (commands,) = (
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(commands.choices)


def _reads_as_submission(command: str, option: str) -> bool:
    """Whether `manuscript-guard <command> <option>` asks for the submission standard."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return bool(build_parser().parse_args([command, option]).submission)
    except SystemExit:
        return False


def test_every_prefix_of_submission_that_is_read_is_one_the_guard_sees() -> None:
    """argparse reads any prefix of an option that names one option only, so `build --subm`
    was a submission build, and the submission guard, whose marker is the whole word, let it
    through in a project that fails. Taken from the parser, so that a command given the
    option later is held to the same.

    It is about the one option. `--stage submission` asks for the same standard and is a
    marker after `build` only: after `check` it is what a refusal tells its reader to run
    (`tests/test_hooks.py`)."""
    from manuscript_guard.hooks import SUBMISSION_MARKERS

    word = "--submission"
    taking = [name for name, parser in _commands().items() if word in parser._option_string_actions]
    assert {"check", "build", "review", "respond"} <= set(taking)

    unseen = [
        f"manuscript-guard {command} {word[:length]}"
        for command in taking
        for length in range(3, len(word) + 1)
        if _reads_as_submission(command, word[:length])
        and not SUBMISSION_MARKERS.search(f"manuscript-guard {command} {word[:length]}")
    ]
    assert unseen == []
    # Not by refusing everything: the word itself is still read.
    assert all(_reads_as_submission(command, word) for command in taking)


def test_no_command_reads_an_abbreviated_option() -> None:
    """The setting is each parser's own: on the top parser alone it leaves every command
    reading abbreviations, and those are where the options are."""
    parser = build_parser()
    abbreviating = [
        name
        for name, command in {"manuscript-guard": parser, **_commands()}.items()
        if command.allow_abbrev
    ]
    assert abbreviating == []


@pytest.mark.parametrize(
    "argv",
    [
        ("build", "--subm", "--offline"),
        ("check", "--subm"),
        ("review", "--subm"),
        ("respond", "--subm"),
        ("build", "--off"),
        ("submit", "--skip"),
    ],
)
def test_an_abbreviated_option_is_an_error_that_names_it(argv: tuple, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        run(*argv)
    assert exit_.value.code == 2
    assert f"unrecognized arguments: {argv[1]}" in capsys.readouterr().err


def test_an_abbreviated_version_prints_no_version(capsys) -> None:
    """Before any command the error is argparse's for the command that is missing, which
    does not name the option. It is an error all the same, and prints no version."""
    with pytest.raises(SystemExit) as exit_:
        run("--vers")
    assert exit_.value.code == 2
    assert capsys.readouterr().out == ""


def test_an_option_written_in_full_is_still_read(project: Path, capsys) -> None:
    assert run("check", str(project), "--submission", "--json") == 0
    assert json.loads(capsys.readouterr().out)["counts"]
