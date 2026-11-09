"""The audit's text report at a glance: what each check found, a line each, before the
sections; the sections with something to show; the findings on the words grouped by kind,
their first places listed and each kind's hint said once; and every place of every finding
behind `--details` (Basile, 2026-11-09: "no one will read the current output").
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.auditing.summary import DETAILS, PLACES, grouped
from manuscript_guard.cli import main
from manuscript_guard.findings import WARN, Finding

#: Ten abbreviations the paper uses once each and defines nowhere.
UNDEFINED = ("ROR", "PRR", "EBGM", "SDR", "BCPNN", "MGPS", "OMOP", "FAERS", "VAERS", "ICSR")
PAPER = (
    "# Abstract\n\nWe read 412 reports.\n\n# Methods\n\n"
    + " ".join(f"The {short} was computed." for short in UNDEFINED)
    + "\n\n# Results\n\nOf 412 reports, 77 were serious.\n"
)


def written(tmp_path: Path, text: str = PAPER) -> Path:
    paper = tmp_path / "paper.md"
    paper.write_text(text, encoding="utf-8")
    return paper


def test_the_report_says_what_each_check_found_before_its_sections(tmp_path: Path, capsys) -> None:
    """The checks that found nothing are a line each at the top, not a section each; the
    findings on the words are grouped by kind, the first places of each listed and its hint
    said once, where 103 findings took three lines each and repeated one hint 90 times."""
    assert main(["audit", str(written(tmp_path))]) == 0
    out = capsys.readouterr().out
    glance = out.index("What was checked:")
    assert glance < out.index("=== Writing (G6) and Language (G14)")
    for name in ("Membership", "Arithmetic", "Small cells", "Writing and language"):
        assert f"\n  {name} " in out[glance:], name
    assert "=== Membership ===" not in out and "=== Arithmetic ===" not in out
    assert "=== Small cells" not in out
    assert f"Abbreviations used and not defined (G14, {len(UNDEFINED)})" in out
    assert out.count("is used once in the main text and not defined there") == PLACES
    assert f"and {len(UNDEFINED) - PLACES} more: {DETAILS} lists every place" in out
    assert out.count("define it at first use") == 1
    assert f"Every place of every finding, with its context and what to do: {DETAILS}." in out


def test_details_print_every_section_and_every_place(tmp_path: Path, capsys) -> None:
    """With `--details`, every section as it was, and each finding with its context and its
    hint."""
    assert main(["audit", str(written(tmp_path)), "--details"]) == 0
    out = capsys.readouterr().out
    assert "What was checked:" in out
    assert "=== Membership ===" in out and "=== Arithmetic ===" in out
    assert out.count("is used once in the main text and not defined there") == len(UNDEFINED)
    assert out.count("define it at first use") == len(UNDEFINED)
    assert "Every place of every finding" not in out


def test_the_summary_says_each_list_and_each_paper_as_it_is(tmp_path: Path, capsys) -> None:
    """Round 1 of #600: a paper with no list and a paper with one are each said, and one
    paper G14 did not run on is said beside another's findings."""
    from manuscript_guard.audit import AuditReport
    from manuscript_guard.auditing.gates import GateRun
    from manuscript_guard.auditing.summary import checks

    found = Finding("G14", "abbreviation-undefined", "ROR is used once", WARN, line=3)
    report = AuditReport(gates=[GateRun(Path("a.md"), language=[found]),
                                GateRun(Path("b.docx"), note="G6 and G14 were not run")])
    (said,) = [line for line in checks(report) if "Writing and language" in line]
    assert "1 finding to look at" in said and "not run on b.docx" in said
    written(tmp_path, "Of 412 reports, 77 were serious.\n")
    main(["audit", str(tmp_path / "paper.md")])
    out = capsys.readouterr().out
    assert "References                no reference list read" in out or "no list read" in out


def test_a_finding_strict_counts_is_never_left_to_the_summary(tmp_path: Path, capsys) -> None:
    """A number found in no output and a total its counts do not add up to are listed in
    their sections, with their places, whatever else is folded away."""
    table = "\n\n| Group | n |\n|---|---|\n| A | 3 |\n| B | 4 |\n| Total | 9 |\n"
    outputs = tmp_path / "out.json"
    outputs.write_text('{"reports": 412}', encoding="utf-8")
    paper = written(tmp_path, PAPER + table)
    main(["audit", str(paper), "--against", str(outputs)])
    out = capsys.readouterr().out
    assert "=== Membership ===" in out and "NOT FOUND IN ANY OUTPUT" in out
    assert "not found (counted by --strict)" in out[: out.index("=== Membership ===")]
    assert "=== Arithmetic ===" in out and "TOTALS THAT THEIR COUNTS DO NOT ADD UP TO" in out
    assert "total off its counts (counted by --strict)" in out


def test_a_kind_whose_places_differ_in_their_hint_gives_each_its_own() -> None:
    """G6's rates are one kind, each with its own reason: said once, the first one's reason
    stood for all."""
    rates = [Finding("G6", "ai-cadence", "boldface: 74 in 6313 words", WARN, hint="bold"),
             Finding("G6", "ai-cadence", "em dashes: 9 in 6313 words", WARN, hint="dashes")]
    lines = grouped(rates, lambda path, line: f"line {line}")
    assert [line.strip() for line in lines if "Hint:" in line] == ["Hint: bold", "Hint: dashes"]
    assert "    the paper: boldface: 74 in 6313 words" in lines


def test_a_place_in_another_file_of_the_paper_names_its_file(tmp_path: Path, capsys) -> None:
    """A LaTeX paper's findings stand in the files it inputs: a place there names its file,
    where "line 3" under the main file's name said the wrong place (round 1 of #600)."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Methods}\n\\input{methods}\n"
        "\\end{document}\n", encoding="utf-8")  # fmt: skip
    (tmp_path / "methods.tex").write_text("Text.\n\nThe ROR was raised in 412 reports.\n",
                                          encoding="utf-8")  # fmt: skip
    main(["audit", str(tmp_path / "main.tex")])
    out = capsys.readouterr().out
    assert "    methods.tex:3: ROR is used once" in out, out


def test_a_failing_finding_on_the_words_says_so_and_a_phrase_shows_its_words() -> None:
    """A failure looks like one in the grouped form, and a finding whose message does not
    quote the text, G6's phrasing, shows the words it matched (round 1 of #600)."""
    from manuscript_guard.findings import FAIL

    found = [Finding("G6", "revision-residue", "a reply to a reviewer", FAIL,
                     line=4, context="as the reviewer asked"),
             Finding("G6", "ai-phrasing", "importance-tail: an -ing tail", WARN,
                     line=9, context="highlighting the value of")]  # fmt: skip
    lines = grouped(found, lambda path, line: f"line {line}")
    assert "    line 4: FAIL: a reply to a reviewer" in lines
    assert "      > highlighting the value of" in lines
