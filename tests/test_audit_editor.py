"""`audit --editor`: an editor's report, each finding in one of four parts by one table.

The parts and the table are the author's (Basile, 2026-11-25): what to look at before deciding,
what to ask the authors, what is for copyediting, and what the check read; the self-citation
counts in the summary line, in no part. Each finding of the first three parts carries how often
findings of its kind were right on the corpus of published papers, where ten or more were
judged. The table is held here to every code the audit can make, read from the source as
`tests/test_finding_keys_source.py` reads it, so a new check cannot land outside the parts.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

from test_finding_keys_source import SRC, made

from manuscript_guard.auditing import NOTICE, READER_FLAGS, by_title, editor
from manuscript_guard.auditing.report import Item
from manuscript_guard.cli import main
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.keys import PAPER_LEVEL

PAPER = (
    "# Active learning in a pharmacology course\n\n"
    "## Abstract\n\n"
    "Of 250 eligible students, 164 (66%) took part. The score rose by 2.4 points.\n\n"
    "## Methods\n\n"
    "We measured the behaviour of each student, and the color of the answer sheets was "
    "recorded. The behavior scale was the one used before.\n\n"
    "## Results\n\n"
    "Of 250 eligible students, 164 (66%) took part. The groups differed, t(29) = 0.50, "
    "P = 0.004.\n\n"
    "## References\n\n"
    "1. Smith J. A cohort. Lancet. 2019;393:100-10.\n"
)


def paper_md(tmp_path: Path, text: str = PAPER) -> Path:
    path = tmp_path / "paper.md"
    path.write_text(text, encoding="utf-8")
    return path


def edited(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(["audit", *argv, "--editor"])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def part_text(out: str, title: str) -> str:
    """The text of one part of the editor's report, from its heading to the next."""
    start = out.index(title)
    following = [out.find(other, start + 1) for _key, other in editor.PARTS]
    ends = [at for at in following if at > start]
    return out[start:min(ends)] if ends else out[start:]


# ------------------------------------------------------------------ the report


def test_each_finding_stands_in_its_part_under_what_the_editor_reads(tmp_path, capsys) -> None:
    code, out, _err = edited(capsys, str(paper_md(tmp_path)))
    assert code == 0
    titles = [title for _key, title in editor.PARTS]
    assert [out.index(title) for title in titles] == sorted(out.index(t) for t in titles)
    look = part_text(out, editor.title(editor.LOOK))
    assert editor.kind_named("numbers-disagree").says in look
    assert "Right in 13 of 13 judged on published papers." in look
    assert "t(29) = 0.50" in look and "P = 0.004" in look
    ask = part_text(out, editor.title(editor.ASK))
    assert editor.kind_named("abstract-not-found").says in ask
    assert "2.4" in ask
    copyedit = part_text(out, editor.title(editor.COPYEDIT))
    assert "A word spelt in the other English: 1, first at paper.md:9." in copyedit
    assert "Right in 133 of 147 judged on published papers." in copyedit
    read = part_text(out, editor.title(editor.READ))
    assert "reference list" in read
    # The summary line counts each part before the first of them.
    top = out[:out.index(editor.title(editor.LOOK))]
    assert "1 to look at before you decide" in top
    assert "to ask the authors" in top and "for copyediting" in top


def test_the_editor_reads_no_gate_and_no_option(tmp_path, capsys) -> None:
    _code, out, _err = edited(capsys, str(paper_md(tmp_path)))
    shown = out[:out.index(editor.title(editor.READ))]
    assert not re.search(r"\bG\d+\b", shown), shown
    assert not re.search(r"(?<![\w-])--[a-z]", shown), shown
    assert "strict" not in shown


def test_the_report_never_says_the_paper_is_clean(tmp_path, capsys) -> None:
    quiet = "# A note\n\n## Abstract\n\nWe read 12 papers.\n\n## Results\n\nWe read 12 papers.\n"
    _code, out, _err = edited(capsys, str(paper_md(tmp_path, quiet)))
    assert "0 to look at before you decide" in out
    assert editor.SCOPE in out
    assert editor.title(editor.READ) in out
    assert "clean" not in out.lower() and "no problem" not in out.lower()


def test_details_lists_every_place_of_the_copyediting(tmp_path, capsys) -> None:
    _code, short, _err = edited(capsys, str(paper_md(tmp_path)))
    _code, full, _err = edited(capsys, str(paper_md(tmp_path)), "--details")
    kind = editor.kind_named("spelling-variant")
    brief = part_text(short, editor.title(editor.COPYEDIT))
    assert "behaviour" not in brief
    listed = part_text(full, editor.title(editor.COPYEDIT))
    assert f"  {kind.says}\n" in listed
    assert "paper.md:9: 'behaviour'" in listed


def test_editor_mode_keeps_the_manuscript_from_a_model(tmp_path, capsys) -> None:
    from manuscript_guard.hooks import _reads_in_confidence

    assert "--editor" in READER_FLAGS
    _code, _out, err = edited(capsys, str(paper_md(tmp_path)))
    assert NOTICE in err
    assert _reads_in_confidence("manuscript-guard audit paper.docx --editor") is not None


def test_the_json_gives_each_finding_its_part_and_kind(tmp_path, capsys) -> None:
    paper = str(paper_md(tmp_path))
    main(["audit", paper, "--json"])
    plain = json.loads(capsys.readouterr().out)
    main(["audit", paper, "--json", "--editor"])
    said = json.loads(capsys.readouterr().out)
    assert all("part" not in finding for finding in plain["findings"])
    assert [f["key"] for f in said["findings"]] == [f["key"] for f in plain["findings"]]
    keys = {key for key, _title in editor.PARTS}
    assert all(finding["part"] in keys | {editor.SUMMARY} for finding in said["findings"])
    assert all(editor.kind_named(finding["kind"]) for finding in said["findings"])
    counted = {key: sum(f["part"] == key for f in said["findings"]) for key in keys}
    assert said["editor"]["parts"] == counted
    assert counted[editor.LOOK] == 1


# ------------------------------------------------------------------ the table


def test_a_record_is_shown_only_where_ten_or_more_were_judged() -> None:
    for kind in editor.KINDS:
        if kind.record is not None:
            true, judged = kind.record
            assert judged >= editor.SHOWN_FROM and 0 <= true <= judged, kind.name
            assert editor.record_said(kind) == (f"Right in {true} of {judged} judged on "
                                                "published papers.")  # fmt: skip
        else:
            assert editor.record_said(kind) == "Not yet measured on published papers."
        assert kind.part != editor.READ or kind.record is None, kind.name


def test_each_kind_has_a_name_of_its_own_and_a_part() -> None:
    names = [kind.name for kind in editor.KINDS]
    assert len(names) == len(set(names))
    assert {kind.part for kind in editor.KINDS} <= {key for key, _t in editor.PARTS} | {
        editor.SUMMARY}
    assert all(kind.says.endswith(".") for kind in editor.KINDS)


def test_the_self_citation_counts_stand_in_the_summary_line_in_no_part() -> None:
    for code in ("self-citation-author", "self-citation-journal"):
        item = Item("Self-citation", "audit", code, "Ada Example: 3 references", INFO, False)
        assert editor.kind_of(item, SimpleNamespace(documents=[])).part == editor.SUMMARY
    author = SimpleNamespace(shown="Ada Example")
    said = SimpleNamespace(note="", looked=38, authors=[(author, [1, 2, 3])],
                           journal="Journal of Examples", in_journal=[1, 2])
    line = editor.self_citation_line(said)
    assert line == ("Self-citation, of 38 references looked up: Ada Example 3; "
                    "Journal of Examples 2.")  # fmt: skip


def _item(code: str, severity: str = WARN, gate: str = "audit", subject: str | None = None,
          path: Path | None = None) -> Item:  # fmt: skip
    return Item("Section", gate, code, "said", severity, severity == FAIL, path,
                subject=subject)


def _facts(path: Path, **held) -> SimpleNamespace:
    kinds = ("insertions", "deletions", "moves", "comments", "hidden", "unseen", "zero_width",
             "to_a_model")
    return SimpleNamespace(path=path, note="", **{k: held.get(k, []) for k in kinds})


def test_three_codes_are_parted_by_what_the_finding_holds() -> None:
    nothing = SimpleNamespace(documents=[])
    assert editor.kind_of(_item("over-header-n", FAIL), nothing).part == editor.LOOK
    assert editor.kind_of(_item("over-header-n", INFO), nothing).part == editor.READ
    for subject, part in (("placeholder-word: xxxx", editor.COPYEDIT),
                          ("placeholder-slot: [url]", editor.COPYEDIT),
                          ("placeholder-word: todo", editor.ASK),
                          ("assistant-voice: Certainly! Here is", editor.ASK),
                          ("placeholder-template: Insert your abstract", editor.ASK)):
        artefact = _item("model-artefact", WARN, "G6", subject)
        assert editor.kind_of(artefact, nothing).part == part, subject
    word = Path("paper.docx")
    for held, part in (({"to_a_model": ["x"]}, editor.LOOK), ({"hidden": ["x"]}, editor.LOOK),
                       ({"zero_width": ["x"]}, editor.LOOK), ({"unseen": ["x"]}, editor.LOOK),
                       ({"insertions": ["x"]}, editor.ASK), ({"comments": ["x"]}, editor.ASK),
                       ({"comments": ["x"], "hidden": ["x"]}, editor.LOOK), ({}, editor.READ)):
        report = SimpleNamespace(documents=[_facts(word, **held)])
        found = _item("document-holds", WARN if held else INFO, path=word)
        assert editor.kind_of(found, report).part == part, held


def test_the_codes_round_1_found_outside_the_table_stand_in_their_parts() -> None:
    """Made through a constructor or a callable the walk did not read (round 1): each in a
    part of its own, none left to `FURTHER`."""
    nothing = SimpleNamespace(documents=[])
    for gate, code, part in (("G14", "abbreviations-passed-over", editor.READ),
                             ("audit", "non-negative-unread", editor.READ),
                             ("audit", "non-negative-unfound", editor.READ),
                             ("G4", "box-items", editor.ASK),
                             ("G4", "box-item-long", editor.ASK),
                             ("G4", "box-over-limit", editor.ASK),
                             ("G4", "box-headings-missing", editor.ASK)):
        kind = editor.kind_of(_item(code, INFO, gate), nothing)
        assert kind is not editor.FURTHER and kind.part == part, code


def test_a_code_with_no_kind_is_put_to_the_authors_not_lost() -> None:
    kind = editor.kind_of(_item("a-code-made-tomorrow"), SimpleNamespace(documents=[]))
    assert kind is editor.FURTHER and kind.part == editor.ASK


# -------------------------------------------------- every code the audit can make has a kind

#: The files and the functions whose findings an audit gives: every finding made in the
#: audit's own modules, G6's and G14's wherever they are made (the audit runs both whole),
#: and G4's where `check_journal(records=False)` and `check_boxes` make them.
AUDIT_FILES = ("audit.py", "auditing/")
WHOLE = ("G6", "G14")
G4_SITES = {f"gates/journal.py:{name}" for name in (
    "_check_freshness", "_check_limits", "_check_abstract_found", "_check_structure",
    "_check_statements")} | {"gates/data_statement.py:judge_statement"}  # fmt: skip
G4_FILES = ("gates/journal_boxes.py",)

#: Codes an audit gives that the walk of `made` does not read as typed, each with the file
#: that names it: a code chosen by a condition, passed on from another module's constant, or
#: given by a call no walk reads as a finding's.
UNREAD = {
    ("audit", "document-holds"): "auditing/report.py",
    ("audit", "document-unreadable"): "auditing/report.py",
    ("audit", "blind-document-names-author"): "build/blinding.py",
    ("audit", "does-not-fit"): "audit.py",
    ("audit", "causal-word-observational"): "auditing/causal.py",
    ("audit", "passed-over"): "auditing/report.py",
    ("audit", "not-audited"): "auditing/report.py",
    ("audit", "headings-read"): "auditing/report.py",
    ("audit", "question-no-abstract"): "auditing/abstract.py",
    ("audit", "question-no-results"): "auditing/abstract.py",
    ("audit", "question-number-only-in"): "auditing/abstract.py",
    ("audit", "question-background-unsourced"): "auditing/abstract.py",
    ("audit", "abstract-answer-contradicted"): "auditing/abstract.py",
    ("audit", "results-heading-unmatched"): "auditing/abstract.py",
    ("audit", "results-heading-not-read"): "auditing/abstract.py",
    ("audit", "results-heading-reports-nothing"): "auditing/abstract.py",
}


#: Codes the walk reads that an audit never gives, each with why.
NEVER = {
    ("G7", "reference-retracted-cited"): "auditing/references.py hands `_standing` no excuse",
}

#: The code-shaped strings of the audit's own modules that are no finding's code, each with
#: what it is (`test_every_code_shaped_string_of_the_audit_is_a_code_with_a_kind`).
NOT_CODES = {
    "author-year": "a citation style (auditing/cited.py, auditing/sentences.py)",
    "package-receipt": "a prefix the draft groups the package's codes by (auditing/draft.py)",
    "package-result": "a prefix the draft groups the package's codes by (auditing/draft.py)",
    "package-verification": "a prefix the draft groups the package's codes by",
    "claim-negation": "compare's code, which measured.py sets the severity of",
    "placeholder-slot": "a rule of G6's model-artefact (auditing/measured.py)",
    "placeholder-word": "a rule of G6's model-artefact (auditing/measured.py)",
    "placeholder-template": "a rule of G6's model-artefact (auditing/summary.py)",
    "manuscript-guard": "the tool's name",
}


def _literal_calls(path: Path, callee: str, function: str | None = None,
                   at: int = 0) -> set[str]:  # fmt: skip
    """The argument at `at`, or the `code` keyword, of each call to `callee`, a name or a
    method, where it is a string or a module constant naming one, in `function` of `path`
    or anywhere in it."""
    from test_finding_keys_source import _constants

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _constants(path)
    scopes = [node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == function] if function \
        else [tree]  # fmt: skip
    found = set()
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != callee:
                continue
            given = {one.arg: one.value for one in node.keywords}
            arg = given.get("code", node.args[at] if len(node.args) > at else None)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in names:
                found.add(names[arg.id])
    return found


def made_by_the_audit() -> set[tuple[str, str]]:
    found = set()
    for gate, code, site, _keyed in made():
        if code.startswith("<") or gate.startswith("<"):
            continue
        file = site.partition(":")[0]
        if file.startswith(AUDIT_FILES) or gate in WHOLE or site in G4_SITES or (
                file in G4_FILES):
            found.add((gate, code))
    found |= {("G6" if code == "ai-cadence" else "G14", code) for code in PAPER_LEVEL}
    found |= {("G14", code) for code in _literal_calls(SRC / "gates" / "language.py",
                                                        "finding")}  # fmt: skip
    found |= {("G7", code) for code in _literal_calls(SRC / "auditing" / "references.py",
                                                       "Problem")}  # fmt: skip
    found |= {("G7", code) for code in _literal_calls(SRC / "gates" / "lookups.py", "_finding",
                                                       "_standing")}  # fmt: skip
    found |= {("G7", code) for code in by_title.CODES.values()}
    found |= {("audit", code) for code in _literal_calls(SRC / "auditing" / "package.py",
                                                          "say")}  # fmt: skip
    # Made through a callable handed in, or a constructor `made` does not read (round 1).
    found |= {("audit", code) for code in _literal_calls(SRC / "auditing" / "skew.py", "item",
                                                          "items", at=2)}  # fmt: skip
    found |= {("G14", code) for name in ("Undefined", "Listed")
              for path in sorted(SRC.rglob("*.py")) for code in _literal_calls(path, name)}
    found |= {("G4", code) for code in _literal_calls(SRC / "gates" / "journal_boxes.py",
                                                       "_at")}  # fmt: skip
    return (found | set(UNREAD)) - set(NEVER)


def test_every_code_the_audit_makes_has_a_kind() -> None:
    parted = {code for kind in editor.KINDS for code in kind.codes}
    missing = sorted(made_by_the_audit() - parted)
    assert not missing, f"no kind in auditing/editor.py for {missing}"


def test_every_kind_names_only_codes_the_audit_makes() -> None:
    parted = {code for kind in editor.KINDS for code in kind.codes}
    stale = sorted(parted - made_by_the_audit())
    assert not stale, f"a kind in auditing/editor.py names codes the audit never makes: {stale}"


def test_every_code_shaped_string_of_the_audit_is_a_code_with_a_kind() -> None:
    """A net under the walk: a code made in the audit's own modules by a way no reading above
    knows still stands in them as a string, and is caught here (round 1: three codes made
    through a callable handed in and a constructor the walk did not read)."""
    shape = re.compile(r"^[a-z]+(?:-[a-z]+)+$")
    parted = {code for kind in editor.KINDS for _gate, code in kind.codes}
    loose = {}
    for path in [SRC / "audit.py", *sorted((SRC / "auditing").glob("*.py"))]:
        if path.name == "editor.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and shape.match(
                    node.value) and node.value not in parted | set(NOT_CODES):
                loose.setdefault(node.value, path.name)
    assert not loose, f"code-shaped strings with no kind and not in NOT_CODES: {loose}"


def test_each_code_the_walk_cannot_read_is_named_in_its_file() -> None:
    for (_gate, code), file in UNREAD.items():
        assert f'"{code}"' in (SRC / file).read_text(encoding="utf-8"), (code, file)
