"""`audit` says the names from the code a paper prints in one finding (`auditing.code_names`).

The corpus run of 2026-11-12 audited 52 real preprints and gave 369 `code-name-in-prose`
warnings, one for each name; judges found 82% of a sample false, and 198 of them came from one
paper's survey variables. The author decided on one finding per paper, made as the one on the
short forms left undefined is (#640, `auditing.undefined`), with `--known` as its remedy and
`check` unchanged (decision 13, 2026-11-13).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from manuscript_guard.auditing import code_names
from manuscript_guard.cli import main
from manuscript_guard.findings import WARN, Finding

#: The shape pdf-med-A1 has: a survey's variables named in the text as the data file names
#: them, one of them twice, a short form beside them.
PAPER = (
    "# Methods\n\n"
    "The item community_action_importance asked how important it was, and "
    "community_action_norms asked what others did. The SIGNA scan was read.\n\n"
    "# Results\n\nThe answers to community_action_importance and to trust_in_science were "
    "high.\n"
)
#: The names the audit lists, in the order the paper first uses them.
LISTED = ("community_action_importance", "community_action_norms", "trust_in_science")


def written(folder: Path, text: str = PAPER, name: str = "paper.md") -> Path:
    paper = folder / name
    paper.write_text(text, encoding="utf-8")
    return paper


def _json(paper: Path, capsys, *flags: str) -> dict:
    assert main(["audit", str(paper), "--json", *flags]) == 0
    return json.loads(capsys.readouterr().out)


def warned(names: tuple[str, ...] = LISTED) -> list[Finding]:
    """G14's warning on each name, as the gate words it, a line apiece."""
    return [Finding("G14", code_names.CODE, f"'{name}' is written with underscores, the way a "
                    "name in code is written, and the reader has never seen it: it is used "
                    "once, first in the prose", WARN, line=at)
            for at, name in enumerate(names, 3)]  # fmt: skip


def test_the_names_from_the_code_are_one_finding_at_the_first_use(tmp_path: Path, capsys) -> None:
    """One finding where there were three: the names in the order of their first use, the
    first quoted where it stands, each with the warning G14 gave it and its place."""
    report = _json(written(tmp_path), capsys)
    (found,) = [f for f in report["findings"] if f["code"] == code_names.CODE]
    assert found["line"] == 3 and "community_action_importance" in found["context"]
    assert found["message"] == (
        "3 names are written the way names in code are, as G14 reads the paper: "
        "'community_action_importance' here, then community_action_norms, trust_in_science"
    ), found["message"]
    assert "--known" in found["hint"] and found["severity"] == "warn"
    assert [form["form"] for form in found["forms"]] == list(LISTED)
    assert [form["line"] for form in found["forms"]] == [3, 3, 7]
    assert found["forms"][0]["message"].startswith(
        "'community_action_importance' is written with underscores, the way a name in code is "
        "written, and the reader has never seen it: it is used 2 times")
    assert "passed_over" not in found
    # The short forms' finding is beside it, as it was.
    assert [f["code"] for f in report["findings"] if f["gate"] == "G14"].count(
        "abbreviation-undefined") == 1


def test_one_name_is_said_in_the_singular(tmp_path: Path, capsys) -> None:
    report = _json(written(tmp_path, "# Methods\n\nThe w_min was set.\n"), capsys)
    (found,) = [f for f in report["findings"] if f["code"] == code_names.CODE]
    assert found["message"] == ("1 name is written the way a name in code is, as G14 reads "
                                "the paper: 'w_min' here")  # fmt: skip


def test_the_summary_counts_the_names_and_details_list_each(tmp_path: Path, capsys) -> None:
    """The kind's line counts the three names, not the one finding; `--details` gives each
    name's first use with G14's words on it, and the paper's line counts them."""
    paper = written(tmp_path)
    main(["audit", str(paper)])
    out = capsys.readouterr().out
    assert "Names from the code in the text (G14, 3)" in out, out
    assert out.count("names are written the way names in code are") == 1
    main(["audit", str(paper), "--details"])
    out = capsys.readouterr().out
    assert "  Each name written the way a name in code is, where it is first used:" in out, out
    assert "    line 7: 'trust_in_science' is written with underscores" in out, out
    assert "paper.md: 0 from G6, 4 from G14" in out, out


def test_known_words_are_taken_off_the_list_of_the_finding(tmp_path: Path, capsys) -> None:
    """`--known`, the finding's remedy, takes a name off it; with every name known, there is
    no finding of names from the code."""
    paper = written(tmp_path)
    report = _json(paper, capsys, "--known", "community_action_norms")
    (found,) = [f for f in report["findings"] if f["code"] == code_names.CODE]
    assert [form["form"] for form in found["forms"]] == [LISTED[0], LISTED[2]]
    report = _json(paper, capsys, "--known", *LISTED)
    assert not [f for f in report["findings"] if f["code"] == code_names.CODE]


def test_the_kinds_rank_by_the_names(tmp_path: Path) -> None:
    """The kind ranks by the names it counts, above a kind of two findings, as the web page's
    tallies count it (`summary.kinds`); the referee draft's row counts them too."""
    from manuscript_guard.audit import AuditReport
    from manuscript_guard.auditing.draft import _checks_of_audit
    from manuscript_guard.auditing.gates import GateRun
    from manuscript_guard.auditing.summary import grouped, kinds

    phrasing = [Finding("G6", "ai-phrasing", "a phrase", WARN, line=at) for at in (1, 2)]
    found = [*phrasing, *code_names.one_finding(warned())]
    lines = grouped(found, lambda path, line: f"line {line}")
    titles = [line.strip() for line in lines if line.startswith("  ") and "(G" in line]
    assert titles[0] == "Names from the code in the text (G14, 3)", titles
    (kind,) = [kind for kind in kinds(found, lambda p, n: "") if kind["code"] == code_names.CODE]
    assert kind["count"] == 3 and len(kind["places"]) == 1
    report = AuditReport(gates=[GateRun(tmp_path / "a.md", language=found[2:])])
    rows = {name: count for name, _said, count in _checks_of_audit(report, [])}
    assert rows["Language (G14) on a.md"] == 3, rows


def test_the_page_draws_one_place_counted_as_the_names(tmp_path: Path, monkeypatch) -> None:
    """The web page's fold for the kind counts the three names and holds one place, its hint
    said once for the kind (`web.view`)."""
    from manuscript_guard import web

    monkeypatch.chdir(tmp_path)
    written(tmp_path)
    view = json.loads(json.dumps(web.view(["audit", "paper.md"])))["view"]
    (kind,) = [kind for paper in view["words"] for kind in paper["kinds"]
               if kind["code"] == code_names.CODE]  # fmt: skip
    assert kind["count"] == len(LISTED) and len(kind["places"]) == 1, kind
    assert kind["hint"] == code_names.HINT and kind["places"][0]["hint"] is None


def test_any_other_finding_is_left_as_it_was() -> None:
    """A warning whose message is not G14's for one name stays a warning of its own, and so
    does every other finding; with no name, nothing changes."""
    other = Finding("G14", code_names.CODE, "a message G14 never wrote", WARN, line=2)
    phrasing = Finding("G6", "ai-phrasing", "a phrase", WARN, line=1)
    found = [phrasing, other, *warned()]
    audited = code_names.one_finding(found)
    assert audited[:2] == [phrasing, other] and len(audited) == 3
    assert code_names.one_finding([phrasing, other]) == [phrasing, other]


def test_the_finding_reads_what_g14_writes_of_each_kind_of_name(tmp_path: Path) -> None:
    """G14's message for a word with underscores, a key of the results and a variable of the
    data dictionary is what the audit reads the name from: a gate reworded under it would
    leave every warning apart, unnoticed."""
    from manuscript_guard.gates.code_names import Names, Prose, judge_code_names
    from manuscript_guard.gates.language import _file

    file = _file(0, Path("main.md"), "The hr_adj rose by age_group and ror.point.\n", [], False)
    prose = [Prose(file.path, file.text, file.printed, file.code, file.line_of, file.tables)]
    names = Names(frozenset({"ror.point"}), {"age_group": "Age group"})
    found = list(judge_code_names(prose, names).findings)
    (one,) = code_names.one_finding(found)
    assert [form for form, _warning in one.forms] == ["hr_adj", "age_group", "ror.point"]


def test_check_in_a_project_still_warns_of_each_name(tmp_path: Path) -> None:
    """`check` is unchanged: G14 gives a warning for each name, on the text the audit gave
    one finding for."""
    from manuscript_guard.auditing.gates import _stage, audit_project
    from manuscript_guard.auditing.undefined import Listed
    from manuscript_guard.gates.language import check_language

    project = audit_project(tmp_path / "project", _stage(written(tmp_path)), None)
    found = [f for f in check_language(project).findings if f.code == code_names.CODE]
    assert [f.message.split("'")[1] for f in found] == list(LISTED)
    assert not any(isinstance(f, Listed) for f in found)


needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


@needs_pandoc
def test_a_docx_s_names_are_placed_and_the_comment_stands_on_the_first(
    tmp_path: Path, capsys
) -> None:
    """In a .docx, the finding and each name it lists are placed by heading and paragraph,
    and the copy with comments puts the finding on the first use of the first name, the word
    its message quotes."""
    from manuscript_guard.docxtext import comment_ranges, word_comments

    written(tmp_path)
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    report = _json(tmp_path / "paper.docx", capsys)
    (found,) = [f for f in report["findings"] if f["code"] == code_names.CODE]
    assert (found["heading"], found["paragraph"]) == ("Methods", 1), found
    assert [(form["heading"], form["paragraph"]) for form in found["forms"]] == [
        ("Methods", 1), ("Methods", 1), ("Results", 1)]
    target = tmp_path / "commented.docx"
    assert main(["audit", str(tmp_path / "paper.docx"), "--commented", str(target)]) == 0
    capsys.readouterr()
    ranges = comment_ranges(target)
    over = [ranges.get(one.identifier) for one in word_comments(target)
            if "names are written the way names in code are" in one.text]  # fmt: skip
    assert over == ["community_action_importance"], over
