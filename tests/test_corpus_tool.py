"""`tools/corpus.py`, which measures judged findings over runs of a corpus and gates a change.

Everything here is a made-up mini corpus written in `tmp_path`: a few papers' reports, the
packets the findings were judged from, the verdicts and a ledger. No real paper's text is in
the repository, and `run` is tried with its install and its steps faked.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "corpus.py"
RUNNER = REPO / "tools" / "corpus_run.py"


def _tool():
    spec = importlib.util.spec_from_file_location("corpus_tool", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["corpus_tool"] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


tool = _tool()
matching = tool.corpus_match


def finding(gate: str, code: str, message: str, severity: str = "warn", line: int | None = 10,
            path: str = "paper.docx", **extra) -> dict:  # fmt: skip
    return {"gate": gate, "code": code, "message": message, "severity": severity,
            "line": line, "path": path, "context": extra.pop("context", None), **extra}  # fmt: skip


#: The judged findings of the mini corpus, by paper and report, in packet order, each with
#: its verdict. The names say what the new run does with each.
JUDGED = {
    ("paper-a", "audit"): [
        (finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5),
         "true"),  # kept, reported
        (finding("G14", "abbreviation-undefined", "XYZ is used 3 times in the main text and "
                 "not defined there", line=20), "true"),  # now in a question: asked
        (finding("G2", "unclassified-number", "42 is typed", line=30), "true"),  # elsewhere
        (finding("G14", "abbreviation-undefined", "QRS is used once in the main text and not "
                 "defined there", line=40), "true"),  # G14 form, other code: elsewhere
        (finding("G6", "model-artefact", "'[INSERT FIGURE 1]' — Unfilled placeholder text",
                 line=50), "true"),  # gone, but the ledger re-judges it false
        (finding("G14", "spelling-variant", "'color' is the American spelling of 'colour'",
                 line=60), "true"),  # gone: lost
        (finding("audit", "not-audited", "paper.docx: Limitations, read as the reference list",
                 severity="info", line=None), "true"),  # a notice, gone
        (finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=70),
         "false"),  # gone before, loud now
    ],
    ("paper-b", "audit"): [
        (finding("audit", "abstract-not-compared", "not compared: no file has a heading that "
                 "names the Abstract", severity="info", line=None), "true"),  # successor
        (finding("G6", "vague-attribution", "'It is known' with no citation nearby", line=8),
         "unclear"),  # not counted
    ],
}

BASE = {
    ("paper-a", "audit"): [
        finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5),
        finding("G14", "abbreviation-undefined", "XYZ is used 3 times in the main text and not "
                "defined there", line=20),
        finding("G2", "unclassified-number", "42 is typed", line=30),
        finding("G14", "abbreviation-undefined", "QRS is used once in the main text and not "
                "defined there", line=40),
        finding("G6", "model-artefact", "'[INSERT FIGURE 1]' — Unfilled placeholder text",
                line=50),
        finding("G14", "spelling-variant", "'color' is the American spelling of 'colour'",
                line=60),
        finding("audit", "not-audited", "paper.docx: Limitations, read as the reference list",
                severity="info", line=None),
    ],
    ("paper-b", "audit"): [
        finding("audit", "abstract-not-compared", "not compared: no file has a heading that "
                "names the Abstract", severity="info", line=None),
    ],
}

NEW = {
    ("paper-a", "audit"): [
        # reported: the same message, with the folder of another run in it
        finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5),
        # asked: the same code, now one question that names the form
        finding("G14", "abbreviation-undefined", "2 short forms are used and never defined: "
                "'XYZ' here, then ABC. Do any of them need defining?", severity="info",
                line=20, question=True, forms=[
                    {"form": "XYZ", "line": 20, "path": "paper.docx",
                     "message": "XYZ is used 3 times in the main text, and not defined there"},
                    {"form": "ABC", "line": 90, "path": "paper.docx",
                     "message": "ABC is used once in the main text, and not defined there"}]),
        # elsewhere: another code's warning at the same line of the same file
        finding("G2", "typed-number", "42 is typed and not bound", line=30),
        # elsewhere: the same short form under another G14 code, at another line
        finding("G14", "abbreviation-used-before-defined", "QRS is used here, and defined later "
                "at Methods, paragraph 2", line=44),
        # the same line as the lost spelling finding, in another file: not its place
        finding("G12", "plan-section-empty", "the plan's question section is empty", line=60,
                path="design/plan.md"),
        # a notice still there, worded otherwise
        finding("audit", "not-audited", "paper.docx: References, read as the reference list",
                severity="info", line=None),
        # the false finding, loud now
        finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=70),
        # matches no judged finding
        finding("G14", "notation-percent", "'%' stands against its number", line=80),
    ],
    ("paper-b", "audit"): [
        finding("audit", "question-no-abstract", "No Abstract was found. Where is it?",
                severity="info", line=None, question=True),
    ],
}

LEDGER = {"decisions": [
    {"id": "marker", "date": "2026-11-11", "by": "the author", "what": "a placement marker",
     "source": "DESIGN.md, \"A placement marker is no slot\"",
     "rejudge": {"verdict": False, "match": [
         {"gate": "G6", "code": "model-artefact", "message": r"\[INSERT FIGURE \d+\]"}]}},
    {"id": "abstract-questions", "date": "2026-11-16", "by": "the author",
     "what": "the audit asks where no Abstract is found", "source": "#697",
     "successor": {"from": "audit/abstract-not-compared",
                   "to": ["audit/question-no-abstract", "audit/question-no-results"],
                   "scope": "paper"}},
]}  # fmt: skip


def write_run(root: Path, name: str, reports: dict) -> None:
    for (slug, report), found in reports.items():
        folder = root / "runs" / name / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{report}.json").write_text(json.dumps({"findings": found}), "utf-8")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus-root"
    packets, verdicts = {}, []
    for (slug, report), items in JUDGED.items():
        paper = packets.setdefault(slug, {"slug": slug, "text": "made up", "reports": {}})
        paper["reports"][report] = {"findings": [f for f, _ in items]}
        verdicts += [{"slug": slug, "report": report, "index": i, "verdict": v,
                      "gate": f["gate"], "code": f["code"]} for i, (f, v) in enumerate(items)]
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    (root / "report" / "packets" / "field.json").write_text(json.dumps(list(packets.values())))
    (root / "report" / "judged" / "field.json").write_text(json.dumps(verdicts))
    write_run(root, "base", BASE)
    write_run(root, "new", NEW)
    return root


def with_ledger(root: Path, ledger: dict = LEDGER) -> Path:
    (root / "report" / "ledger.yaml").write_text(yaml.safe_dump(ledger), "utf-8")
    return root


def states(result: dict) -> dict[tuple[str, int], str]:
    return {(r["slug"], r["index"]): r["state"] for r in result["findings"]}


def test_each_judged_finding_is_put_in_one_of_four_states(corpus: Path) -> None:
    result = tool.measure(corpus, "new", ledger=False)
    assert states(result) == {
        ("paper-a", 0): "reported", ("paper-a", 1): "asked", ("paper-a", 2): "elsewhere",
        ("paper-a", 3): "elsewhere", ("paper-a", 4): "gone", ("paper-a", 5): "gone",
        ("paper-a", 6): "gone", ("paper-a", 7): "reported", ("paper-b", 0): "gone",
    }  # fmt: skip
    assert result["skipped"] == {"verdict unclear": 1}
    assert result["totals"]["true"] == {"reported": 1, "asked": 1, "elsewhere": 2, "gone": 4}


def test_a_finding_is_found_in_the_run_it_was_judged_from(corpus: Path) -> None:
    result = tool.measure(corpus, "base", ledger=False)
    assert "gone" not in {r["state"] for r in result["findings"] if r["slug"] == "paper-a"
                          and r["index"] < 7}  # fmt: skip


def test_a_note_of_the_same_finding_is_asked_and_a_warning_reported() -> None:
    old = finding("G7", "doi-unresolved", "10.1/abc does not resolve")
    assert matching.state(old, [{**old, "severity": "info"}])[0] == "asked"
    assert matching.state(old, [{**old, "severity": "fail"}])[0] == "reported"
    question = {**old, "code": "question-doi", "severity": "info"}
    assert matching.state(old, [{**question, "message": "Does 10.1/abc resolve?"}])[0] == "asked"
    assert matching.state(old, [{**question, "message": "Is it cited?"}])[0] == "gone"


def test_a_folder_of_the_machine_in_a_message_does_not_tell_two_findings_apart() -> None:
    old = finding("G7", "x", r"C:\Users\someone\scratch\runs\one\paper\project\main.md: read")
    new = finding("G7", "x", "/home/other/runs/two/paper/project/main.md: read")
    assert matching.state(old, [new])[0] == "reported"


def test_the_same_line_of_another_file_is_not_the_same_place() -> None:
    old = finding("G14", "spelling-variant", "'color'", line=60, path="manuscript/main.md")
    other = finding("G12", "plan-section-empty", "'color' here", line=60, path="design/plan.md")
    assert matching.state(old, [other])[0] == "gone"
    # Two files of one name in two folders are two files.
    assert matching.state(old, [{**other, "path": "appendix/main.md"}])[0] == "gone"
    # The same file, wherever the run was made, is the same file.
    there = {**other, "path": "/home/someone/runs/r1/paper-x/project/manuscript/main.md"}
    assert matching.state(old, [there], "paper-x")[0] == "elsewhere"
    # A finding that names no file is at the place only of another that names none.
    assert matching.state(old, [{**other, "path": None}])[0] == "gone"
    assert matching.state({**old, "path": None}, [{**other, "path": None}])[0] == "elsewhere"


def test_a_lost_finding_is_not_kept_by_another_of_its_form_in_another_part() -> None:
    abstract = finding("G14", "abbreviation-undefined", "SHAP is used 2 times in the abstract "
                       "and not defined there", line=3)  # fmt: skip
    main_text = finding("G14", "abbreviation-undefined", "SHAP is used 7 times in the main "
                        "text and not defined there", line=40)  # fmt: skip
    assert matching.states([abstract, main_text], [main_text]) == [("gone", []),
                                                                ("reported", [0])]  # fmt: skip
    assert matching.state(abstract, [main_text])[0] == "gone"
    # One question that lists the form twice, once for each part, answers both.
    question = finding("G14", "abbreviation-undefined", "2 short forms are used and never "
                       "defined: 'SHAP' (in the abstract) here, then SHAP", "info", line=1,
                       question=True, forms=[
                           {"form": "SHAP", "line": 3, "message": abstract["message"]},
                           {"form": "SHAP", "line": 40, "message": main_text["message"]}])
    assert matching.states([abstract, main_text], [question]) == [("asked", [0]), ("asked", [0])]
    assert matching.states([abstract, main_text], [{**question, "forms": question["forms"][1:]}]
                       ) == [("gone", []), ("asked", [0])]  # fmt: skip


def test_the_only_finding_of_its_code_is_found_again_where_its_line_moved() -> None:
    old = finding("G14", "notation-percent", "'%' stands after a space 2 times, as in '24.6 %'",
                  line=91)  # fmt: skip
    now = finding("G14", "notation-percent", "'%' stands after a space 3 times, as in '27.6 %'",
                  line=33)  # fmt: skip
    assert matching.states([old], [now], alone=frozenset({0})) == [("reported", [0])]
    # Not where the judged run had others of its code, nor where the new one has two.
    assert matching.states([old], [now])[0][0] == "gone"
    assert matching.states([old], [now, {**now, "line": 70}], alone=frozenset({0}))[0][0] == "gone"


def test_a_name_listed_with_others_is_found_again_by_the_name() -> None:
    old = finding("G14", "code-name-in-prose", "'max_p' is written as a name in code is, with "
                  "underscores: it is used 5 times, first in the prose", line=13)  # fmt: skip
    grouped = finding("G14", "code-name-in-prose", "2 names are written the way names in code "
                      "are: 'n_top' here, then max_p", line=17, forms=[
                          {"form": "n_top", "line": 17, "message": "'n_top' is written ..."},
                          {"form": "max_p", "line": 21, "message": "'max_p' is written ..."}])
    assert matching.state(old, [grouped]) == ("reported", [0])
    other = {**old, "message": old["message"].replace("max_p", "min_q")}
    assert matching.states([old, other], [grouped]) == [("reported", [0]), ("gone", [])]


def test_a_finding_paired_with_one_keeps_no_other_of_its_code_at_the_place() -> None:
    a = finding("G8", "p-inconsistent", "t(29) = 3.11 gives a P of 0.004, the text says "
                "P = 0.013", line=5)  # fmt: skip
    b = finding("G8", "p-inconsistent", "t(29) = 2.05 gives a P of 0.049, the text says "
                "P = 0.20", line=5)  # fmt: skip
    assert matching.states([a, b], [a]) == [("reported", [0]), ("gone", [])]
    # Nor does a finding of its own code that no judged one took, though it names the word,
    # at another line: that is no other code's warning at its place.
    moved = {**a, "line": 9}
    assert matching.states([b], [moved])[0] == ("gone", [])


def test_a_statistic_is_found_by_its_value_as_typed_never_by_its_degrees_of_freedom() -> None:
    a = finding("G8", "p-inconsistent", "t(29) = 3.11 gives a P of 0.004, the text says "
                "P = 0.013", line=5)  # fmt: skip
    b = finding("G8", "p-inconsistent", "t(29) = 2.05 gives a P of 0.049, the text says "
                "P = 0.20", line=5)  # fmt: skip
    reworded = {**a, "message": "t(29)=3.11 gives P between 0.0041 and 0.0042, and the text "
                "says P = 0.013"}  # fmt: skip
    assert matching.states([b, a], [reworded]) == [("gone", []), ("reported", [0])]
    assert matching.states([a, b], [reworded]) == [("reported", [0]), ("gone", [])]
    key = matching.key_of(finding("audit", "does-not-fit", "F(2, 55) = 0.62 gives a P"))
    assert key.search("that F(2,55)=0.62 gives on its own") and not key.search("F(2, 55) = 0.621")
    assert matching.key_of(finding("x", "y", "the text says P = 0.20")).search("P=0.20 is")
    chi = matching.key_of(finding("x", "y", "\N{GREEK SMALL LETTER CHI}2(1) = 3.84 gives P"))
    assert chi.search("\N{GREEK SMALL LETTER CHI}2 (1) = 3.84") and not chi.search("(1) = 3.84")


def test_a_statistic_is_read_in_the_forms_the_package_writes() -> None:
    def key(message: str):
        return matching.key_of(finding("G8", "p-inconsistent", message))

    chi = key("chi-squared(1) = 3.84 gives a P of 0.050, and the text says P < 0.001")
    assert chi.search("chi-squared(1)=3.84") and not chi.search("P < 0.001 only")
    assert key("z = 2.10 gives a P of 0.036").search("that z = 2.10 gives")
    assert not key("z = 2.10 gives a P of 0.036").search("z = 2.105")
    minus = key("t(29) = \N{MINUS SIGN}2.05 gives a P of 0.049")
    assert minus.search("t(29) = -2.05") and not minus.search("t(29) = 2.05")
    # One "P < 0.001" in two sentences' findings: the statistic tells them apart.
    a = finding("G8", "p-inconsistent", "chi-squared(1) = 3.84 gives a P of 0.050, and the text "
                "says P < 0.001", line=12, context="both tests were significant")  # fmt: skip
    b = {**a, "message": "chi-squared(2) = 9.21 gives a P of 0.010, and the text says P < 0.001"}
    reworded = {**b, "message": "chi-squared(2) = 9.21 gives a P between 0.0099 and 0.0101, "
                "and the text says P < 0.001"}  # fmt: skip
    assert matching.states([a, b], [reworded]) == [("gone", []), ("reported", [0])]


def test_a_value_ends_where_its_digits_end_and_a_middle_dot_is_a_point() -> None:
    dot = matching.key_of(finding("x", "y", "F(2, 55) = 0\N{MIDDLE DOT}62 gives a P"))
    assert dot.search("F(2, 55) = 0\N{MIDDLE DOT}62") and dot.search("F(2, 55) = 0.62")
    assert not dot.search("F(2, 55) = 0")
    whole = matching.key_of(finding("x", "y", "t(29) = 2 gives a P of 0.05"))
    assert whole.search("t(29) = 2 gives") and not whole.search("t(29) = 2.05")
    assert not whole.search("t(29) = 2\N{MIDDLE DOT}05")


def test_a_context_unshared_is_not_the_finding_of_another_form() -> None:
    sentence = "the XYZ and QRS scores were compared"
    xyz = finding("G14", "abbreviation-undefined", "XYZ is used once in the main text and not "
                  "defined there", line=20, context=sentence)  # fmt: skip
    qrs = {**xyz, "message": xyz["message"].replace("XYZ", "QRS")}
    assert matching.states([xyz], [qrs]) == [("gone", [])]


def test_a_shared_context_with_nothing_to_name_takes_nothing() -> None:
    generic = "the plan's question section is a heading with nothing under it"
    a = finding("G12", "plan-section-empty", generic, line=5, context="## Plan")
    b = {**a, "line": 6}
    reworded = {**a, "message": "the plan's section has a heading and no text", "line": 30}
    assert matching.key_of(a) is None
    assert matching.states([a, b], [reworded]) == [("gone", []), ("gone", [])]


def test_a_context_shared_keeps_only_the_finding_its_message_names() -> None:
    sentence = "the XYZ and QRS scores were compared"
    xyz = finding("G14", "abbreviation-undefined", "XYZ is used once in the main text and not "
                  "defined there", line=20, context=sentence)  # fmt: skip
    qrs = finding("G14", "abbreviation-undefined", "QRS is used once in the main text and not "
                  "defined there", line=20, context=sentence)  # fmt: skip
    grouped = finding("G14", "abbreviation-undefined", "1 short form is used and never "
                      "defined: 'XYZ' here. Does it need defining?", "info", line=20,
                      context=sentence, question=True, forms=[{"form": "XYZ"}])
    assert matching.states([xyz, qrs], [grouped]) == [("asked", [0]), ("gone", [])]
    before = finding("G14", "abbreviation-used-before-defined", "XYZ is used here, and defined "
                     "later at Methods", line=20, context=sentence)  # fmt: skip
    other = {**before, "message": "QRS is used here, and defined later at Methods"}
    reworded = {**other, "message": "QRS is used here, and defined later at Results, "
                "paragraph 2", "line": 22}  # fmt: skip
    assert matching.states([before, other], [reworded]) == [("gone", []), ("reported", [0])]
    # A context no other finding of the code shares is the finding's own, whatever its
    # numbers now: a rate whose count of words moved with an edit is the same rate.
    rate = finding("G6", "ai-cadence", "negative-parallelism: 9 in 8539 words (1.1 per 1000)",
                   line=None, context="not just in enrollment but")  # fmt: skip
    vocabulary = {**rate, "message": "ai-vocabulary: 34 in 8539 words", "context": "enhance"}
    now = [{**vocabulary, "message": "ai-vocabulary: 34 in 8526 words"},
           {**rate, "message": "negative-parallelism: 9 in 8526 words (1.1 per 1000)"}]
    assert matching.states([vocabulary, rate], now) == [("reported", [0]), ("reported", [1])]


def test_the_context_at_its_place_comes_before_a_message_alone() -> None:
    generic = "the plan's question section is a heading with nothing under it"
    a = finding("G12", "plan-section-empty", generic, line=5, context="Question")
    b = finding("G12", "plan-section-empty", generic, line=6, context="Outcome")
    new = [{**b, "line": 70}, {**a, "line": 80}]
    assert matching.states([a, b], new) == [("reported", [1]), ("reported", [0])]


def test_an_apostrophe_in_a_word_opens_no_quote() -> None:
    old = finding("audit", "does-not-fit", "the paper's text says P = .61 for the second test")
    assert matching.quoted(old["message"]) == []
    key = matching.key_of(old)
    assert key is not None and key.search("P = .61 is larger") and not key.search("P = .612")
    assert matching.quoted("'color' and \"colour\" and `x_y`") == ["color", "colour", "x_y"]


def test_the_only_finding_of_its_code_is_alone_where_its_word_tells_it_apart(
        tmp_path: Path) -> None:  # fmt: skip
    root = tmp_path / "corpus-root"
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    percent = finding("G14", "notation-percent", "'%' stands after a space 2 times")
    doi = finding("G7", "doi-unresolved", "10.1/abc does not resolve")
    papers = [
        {"slug": "p1", "reports": {"audit": {
            "totals": {"G14/notation-percent": 1, "G7/doi-unresolved": 1},
            "findings": [percent, doi]}}},
        {"slug": "p2", "reports": {"audit": {
            "totals": {"G14/notation-percent": 1, "G7/doi-unresolved": 2},
            "findings": [finding("G14", "notation-percent", "'%' stands against its number"),
                         finding("G7", "doi-unresolved", "10.2/xyz does not resolve")]}}},
    ]  # fmt: skip
    (root / "report" / "packets" / "f.json").write_text(json.dumps(papers))
    verdicts = [{"slug": s, "report": "audit", "index": i, "verdict": "true"}
                for s in ("p1", "p2") for i in (0, 1)]  # fmt: skip
    (root / "report" / "judged" / "f.json").write_text(json.dumps(verdicts))
    judged, _ = tool.load_judged(root)
    alone = {(j.slug, j.finding["code"]): j.alone for j in judged}
    assert alone == {("p1", "notation-percent"): False,  # '%' stands in every one of its code
                     ("p1", "doi-unresolved"): True,
                     ("p2", "notation-percent"): False,
                     ("p2", "doi-unresolved"): False}  # two of its code in its report


def test_a_finding_with_no_file_is_not_at_the_place_of_one_with_a_file() -> None:
    old = finding("G7", "doi-unresolved", "10.1/abc does not resolve", line=4, path=None)
    question = finding("G7", "question-doi", "Does 10.1/abc resolve?", "info", line=4,
                       path="manuscript/main.md", question=True)  # fmt: skip
    assert matching.state(old, [question])[0] == "gone"
    assert matching.state(old, [{**question, "path": None}])[0] == "asked"


def test_two_findings_of_one_message_take_one_finding_each() -> None:
    first = finding("G8", "p-inconsistent", "t(29) = 3.11 gives a P of 0.004, the text says "
                    "P = 0.013", line=5)  # fmt: skip
    second = {**first, "line": 50}
    said = matching.states([first, second], [second])
    assert said == [("gone", []), ("reported", [0])]
    assert matching.states([first, second], [second, first]) == [("reported", [1]),
                                                             ("reported", [0])]  # fmt: skip


def test_a_question_or_warning_at_the_place_keeps_only_what_it_names() -> None:
    lost = finding("audit", "does-not-fit", "F(2, 55) = 0.62 gives a P between 0.539 and 0.544, "
                   "and the text says P = .61", line=66)  # fmt: skip
    question = finding("G14", "abbreviation-undefined", "3 short forms are used and never "
                       "defined: 'ASC' here, then AQ, IQ. Do any of them need defining?",
                       "info", line=66, question=True)  # fmt: skip
    phrasing = finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=66)
    assert matching.state(lost, [question])[0] == "gone"
    assert matching.state(lost, [phrasing])[0] == "gone"
    asks = finding("audit", "question-p-adjusted", "The paper says its P values are adjusted. "
                   "P = .61 is larger than the 0.539 to 0.544 that F(2, 55) = 0.62 gives on "
                   "its own. Is it the adjusted P?", "info", line=66, question=True)
    assert matching.state(lost, [question, phrasing, asks]) == ("asked", [2])


def test_a_finding_said_under_another_code_at_another_line_is_gone() -> None:
    old = finding("compare", "fact-gone", "'0.48' is gone: it stood on line 19 of v1", "info",
                  line=19, path="v2.tex")  # fmt: skip
    now = finding("compare", "table-changed", "Table 6: the row '0.089 B & 0.48 M' is gone",
                  "info", line=40, path="v2.tex")  # fmt: skip
    assert matching.state(old, [now])[0] == "gone"


def test_the_reading_notices_are_counted_apart(corpus: Path) -> None:
    result = tool.measure(corpus, "new", ledger=False)
    assert result["notices"]["true"]["gone"] == 2  # not-audited, abstract-not-compared
    assert result["paper"]["true"]["gone"] == 2
    text = tool.render_measure(result)
    paper_part = text.split("## True findings gone, about the paper")[1].split("## True")[0]
    assert "spelling-variant" in paper_part and "not-audited" not in paper_part


def test_a_rejudge_by_matcher_changes_the_verdict_and_a_successor_asks(corpus: Path) -> None:
    result = tool.measure(with_ledger(corpus), "new")
    rows = {(r["slug"], r["index"]): r for r in result["findings"]}
    marker = rows[("paper-a", 4)]
    assert (marker["judged"], marker["verdict"], marker["rejudged_by"]) == ("true", "false",
                                                                           "marker")  # fmt: skip
    assert rows[("paper-b", 0)]["state"] == "asked"
    assert rows[("paper-b", 0)]["successor_by"] == "abstract-questions"
    assert result["decisions"] == [
        {"id": "marker", "matched": 1, "changed": 1, "successor": 0},
        {"id": "abstract-questions", "matched": 0, "changed": 0, "successor": 1}]
    assert "2 decisions, 1 findings re-judged, 1 kept by a successor" in tool.render_measure(
        result)


def test_a_rejudge_by_key_names_one_finding(corpus: Path) -> None:
    ledger = {"decisions": [{"id": "k", "date": "2026-11-19", "by": "the author",
                             "what": "one finding", "source": "#1", "rejudge": {
                                 "verdict": "false",
                                 "findings": [{"slug": "paper-a", "report": "audit",
                                               "index": 5}]}}]}  # fmt: skip
    rows = tool.measure(with_ledger(corpus, ledger), "new")["findings"]
    assert [r["index"] for r in rows if r["rejudged_by"] == "k"] == [5]


def test_a_successor_needs_its_code_in_the_same_report_of_the_same_paper(corpus: Path) -> None:
    write_run(corpus, "other", {("paper-b", "audit"): [], ("paper-a", "audit"): [
        finding("audit", "question-no-abstract", "Where?", severity="info")]})
    assert states(tool.measure(with_ledger(corpus), "other"))[("paper-b", 0)] == "gone"


@pytest.mark.parametrize(("broken", "says"), [
    ({"decisions": {"id": "x"}}, "a list under `decisions`"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s"}]},
     "one of rejudge or successor"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w",
                     "rejudge": {"verdict": "false", "findings": []}}]}, "`source` is missing"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "rejudge": {"verdict": "maybe", "match": [{"code": "c"}]}}]},
     "true or false"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "rejudge": {"verdict": "false"}}]}, "names no finding"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "rejudge": {"verdict": "false", "match": [{"message": "("}]}}]},
     "no regular expression"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "successor": {"from": "a/b", "to": ["c/d"], "scope": "sentence"}}]},
     "scope"),
])  # fmt: skip
def test_a_ledger_that_is_not_as_written_down_is_refused(corpus: Path, broken: dict,
                                                         says: str) -> None:  # fmt: skip
    with pytest.raises(tool.CorpusError, match=re.escape(says)):
        tool.measure(with_ledger(corpus, broken), "new")


def test_the_gate_fails_on_a_true_finding_kept_at_base_and_gone_now(corpus: Path) -> None:
    result = tool.gate(with_ledger(corpus), "base", "new")
    assert not result["ok"]
    assert [(r["code"], r["base"], r["state"]) for r in result["lost"]] == [
        ("G14/spelling-variant", "reported", "gone")]
    assert tool.main(["--corpus", str(corpus), "gate", "base", "new"]) == 1


def test_the_gate_passes_where_the_author_s_decision_covers_the_loss(corpus: Path) -> None:
    ledger = {"decisions": [*LEDGER["decisions"], {
        "id": "spelling", "date": "2026-11-19", "by": "the author", "what": "w",
        "source": "#2", "rejudge": {"verdict": "false", "match": [
            {"code": "spelling-variant", "slug": "paper-a"}]}}]}  # fmt: skip
    out = corpus / "gate.md"
    assert tool.main(["--corpus", str(with_ledger(corpus, ledger)), "gate", "base", "new",
                      "--out", str(out), "--json", str(corpus / "gate.json")]) == 0  # fmt: skip
    text = out.read_text("utf-8")
    assert "**Passes**" in text
    data = json.loads((corpus / "gate.json").read_text("utf-8"))
    # Without the ledger the marker would be lost too; re-judged false, it is not true.
    assert data["lost"] == []
    assert [r["code"] for r in data["false_loud"]] == ["G6/ai-phrasing"]
    assert [r["code"] for r in data["quieter"]] == ["G14/abbreviation-undefined"]
    # The successor's question stands where the base had the note itself: asked at both.
    assert [r["code"] for r in data["notices"]] == ["audit/not-audited"]
    assert data["unjudged"]["G14/notation-percent"] == {"base": 0, "new": 1}


def test_a_notice_lost_does_not_fail_the_gate(corpus: Path) -> None:
    ledger = {"decisions": [{"id": "all", "date": "d", "by": "the author", "what": "w",
                             "source": "s", "rejudge": {"verdict": "false", "match": [
                                 {"code": "spelling-variant"}, {"code": "model-artefact"}]}}]}
    result = tool.gate(with_ledger(corpus, ledger), "base", "new")
    assert result["ok"]
    assert any(r["code"] == "audit/not-audited" and r["state"] == "gone"
               for r in result["notices"])  # fmt: skip


def test_the_command_says_what_it_needs_in_one_line(tmp_path: Path, capsys,
                                                    monkeypatch) -> None:  # fmt: skip
    monkeypatch.delenv(tool.ENV, raising=False)
    assert tool.main(["measure", "x"]) == 2
    assert tool.ENV in capsys.readouterr().err
    assert tool.main(["--corpus", str(tmp_path), "measure", "x"]) == 2
    assert "not a corpus" in capsys.readouterr().err


def test_a_worktree_guards_the_main_working_tree_too(tmp_path: Path) -> None:
    main = tmp_path / "checkout"
    gitdir = main / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n")
    worktree = main / ".claude" / "worktrees" / "wt"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")
    assert tool.checkouts(worktree) == {worktree.resolve(), main.resolve()}
    assert tool.in_a_checkout(main / "gate.md", root=worktree)
    assert tool.in_a_checkout(worktree / "x" / "gate.md", root=worktree)
    assert not tool.in_a_checkout(tmp_path / "corpus" / "gate.md", root=worktree)
    # A checkout that is no worktree guards itself.
    assert tool.checkouts(tmp_path / "plain") == {(tmp_path / "plain").resolve()}


def test_nothing_the_tool_writes_lands_in_the_checkout(corpus: Path, capsys) -> None:
    inside = REPO / "corpus-gate.md"
    assert tool.main(["--corpus", str(corpus), "gate", "base", "new", "--out", str(inside)]) == 2
    assert "inside the manuscript-guard checkout" in capsys.readouterr().err
    assert not inside.exists()
    assert tool.main(["--corpus", str(corpus), "measure", "new", "--json",
                      str(REPO / "tools" / "m.json")]) == 2  # fmt: skip
    assert tool.main(["--corpus", str(REPO / "no-corpus-here"), "measure", "new"]) == 2
    assert "keep the corpus" in capsys.readouterr().err


def test_the_reading_notices_are_the_ones_the_page_lists_and_the_package_writes() -> None:
    page = (REPO / "docs" / "corpus.md").read_text("utf-8")
    table = page.split("### Reading notices")[1].split("\n## ")[0]
    listed = set(re.findall(r"^\| `([a-z-]+)` \|", table, flags=re.M))
    assert listed == set(tool.NOTICES)
    source = "\n".join(p.read_text("utf-8") for p in (REPO / "src").rglob("*.py"))
    unwritten = [code for code in tool.NOTICES if f'"{code}"' not in source]
    assert not unwritten, f"no code of the package writes {unwritten}"


def test_every_command_the_tool_runs_has_a_time_limit() -> None:
    text = TOOL.read_text("utf-8") + RUNNER.read_text("utf-8")
    tree = ast.parse(text)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "communicate", "check_output", "call")
             and isinstance(n.func.value, ast.Name)
             and n.func.value.id in ("subprocess", "proc")]  # fmt: skip
    assert calls
    for call in calls:
        assert "timeout" in {k.arg for k in call.keywords}, ast.unparse(call)
    assert not re.search(r"subprocess\.(check_call|check_output|getoutput|call)\(", text)


# --- run, with the install and the steps faked ------------------------------------------


def _archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        data = b"[project]\nname = 'stand-in'\n"
        info = tarfile.TarInfo("pyproject.toml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"


class FakeBuild:
    """`quiet` and `call` of the runner, faked: git answers `self.sha`, a venv is a file, and
    each step writes an empty report."""

    def __init__(self, monkeypatch) -> None:
        self.sha, self.quiet_calls, self.steps = SHA, [], []
        monkeypatch.setattr(tool.corpus_run, "quiet", self.quiet)
        monkeypatch.setattr(tool.corpus_run, "call", self.call)

    def quiet(self, cmd, cwd=None) -> bytes:
        self.quiet_calls.append([str(c) for c in cmd])
        if "rev-parse" in cmd:
            return (self.sha + "\n").encode()
        if "archive" in cmd:
            return _archive()
        if "-c" in cmd:
            return b"0.2.999\n"
        if "venv" in cmd:
            python = tool.corpus_run.venv_python(Path(cmd[-1]))
            python.parent.mkdir(parents=True)
            python.write_text("")
        return b""

    def call(self, cmd, cwd, out, env) -> dict:
        self.steps.append((list(cmd), Path(cwd), Path(out), env))
        if "init" in cmd and "--latex" in cmd:
            (Path(cmd[-1]) / "manuscript").mkdir(parents=True)
        out.write_text(json.dumps({"findings": []}))
        return {"cmd": cmd, "exit": 0, "seconds": 0.0, "stderr": ""}


def add_papers(corpus: Path) -> None:
    for slug, meta in {
        "doc-1": {"format": "docx", "main": "paper.docx"},
        "tex-1": {"format": "latex", "main": "latest/paper.tex", "v1": "v1/paper.tex",
                  "pdf": "paper.pdf"},
        "pdf-1": {"format": "pdf", "main": "paper.pdf"},
    }.items():  # fmt: skip
        folder = corpus / "corpus" / slug
        (folder / "files" / "latest").mkdir(parents=True)
        (folder / "files" / "latest" / "paper.tex").write_text("\\section{A}\n")
        (folder / "files" / "latest" / "refs.bib").write_text("@article{a,title={A}}\n")
        (folder / "meta.json").write_text(json.dumps({"slug": slug, **meta}))


def test_run_installs_the_commit_and_runs_each_report_outside_the_papers(
        corpus: Path, monkeypatch) -> None:  # fmt: skip
    add_papers(corpus)
    fake = FakeBuild(monkeypatch)
    monkeypatch.setenv("MANUSCRIPT_GUARD_DEBUG", "1")
    record = tool.corpus_run.run(corpus, "main", "pr-1", REPO, jobs=2, only=None)
    assert record == {"commit": "main", "sha": SHA, "version": "0.2.999", "papers": 3,
                      "scheme": 1, "repo": str(REPO)}  # the fake keys.py names no SCHEME
    assert any("archive" in c and SHA in c for c in fake.quiet_calls)
    assert (corpus / "builds" / SHA[:9] / "installed.txt").read_text("utf-8") == SHA
    assert (corpus / "builds" / f"src-{SHA[:9]}" / "pyproject.toml").is_file()
    papers = (corpus / "corpus").resolve()
    for cmd, cwd, out, env in fake.steps:
        assert cmd[1:5] == ["-I", "-X", "utf8", "-c"], cmd
        assert papers not in cwd.resolve().parents and cwd.resolve() != papers
        assert out.resolve().is_relative_to((corpus / "runs" / "pr-1").resolve())
        assert "MANUSCRIPT_GUARD_DEBUG" not in env
        assert env["MANUSCRIPT_GUARD_NO_REPORTS"] == "1"
    names = {(out.parent.name, out.name) for _, _, out, _ in fake.steps}
    assert names == {
        ("doc-1", "audit.json"), ("doc-1", "init.out"), ("doc-1", "check.json"),
        ("tex-1", "audit.json"), ("tex-1", "audit-pdf.json"), ("tex-1", "compare.json"),
        ("tex-1", "init.out"), ("tex-1", "check.json"), ("pdf-1", "audit.json")}
    project = corpus / "runs" / "pr-1" / "tex-1" / "project"
    assert (project / "manuscript" / "main.tex").is_file()
    assert (project / "literature" / "references.bib").is_file()
    held = json.loads((corpus / "runs" / "pr-1" / "doc-1" / "steps.json").read_text("utf-8"))
    assert held["sha"] == SHA and set(held["steps"]) == {"audit", "init", "check"}
    # A second run of the same build runs no step again and installs nothing.
    fake.steps.clear()
    fake.quiet_calls.clear()
    tool.corpus_run.run(corpus, "main", "pr-1", REPO, jobs=1, only=["doc-1"])
    assert fake.steps == []
    assert not any("archive" in c for c in fake.quiet_calls)


def test_a_run_folder_made_for_another_commit_is_refused(corpus: Path, monkeypatch) -> None:
    add_papers(corpus)
    fake = FakeBuild(monkeypatch)
    tool.corpus_run.run(corpus, "pr", "pr-1", REPO, jobs=1, only=None)
    fake.sha = OTHER_SHA
    fake.steps.clear()
    with pytest.raises(tool.CorpusError, match="holds a run of 012345678, not of fedcba987"):
        tool.corpus_run.run(corpus, "pr", "pr-1", REPO, jobs=1, only=None)
    assert fake.steps == []
    # Its papers' steps are refused too, where run.json is gone.
    (corpus / "runs" / "pr-1" / "run.json").unlink()
    with pytest.raises(tool.CorpusError, match="written for another commit than fedcba987"):
        tool.corpus_run.run(corpus, "pr", "pr-1", REPO, jobs=1, only=None)
    assert fake.steps == []
    # Under its own name, the other commit runs.
    tool.corpus_run.run(corpus, "pr", None, REPO, jobs=1, only=["pdf-1"])
    assert [out.parent.parent.name for _, _, out, _ in fake.steps] == [OTHER_SHA[:9]]


@pytest.mark.parametrize("slug", ["../escape", "doc-2", "a b", ".."])
def test_a_slug_names_its_own_folder_and_nothing_outside(corpus: Path, slug: str) -> None:
    folder = corpus / "corpus" / "doc-1"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"slug": slug, "format": "docx",
                                                  "main": "paper.docx"}))  # fmt: skip
    with pytest.raises(tool.CorpusError, match="is not its folder's name"):
        tool.corpus_run.papers(corpus)


def test_a_commit_that_begins_with_a_dash_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(tool.corpus_run, "quiet", lambda *a, **k: pytest.fail("ran git"))
    with pytest.raises(tool.CorpusError, match="would reach git as an option"):
        tool.corpus_run.resolve(REPO, "--upload-pack=x")


def test_a_ledger_key_whose_index_is_no_number_is_refused(corpus: Path) -> None:
    ledger = {"decisions": [{"id": "k", "date": "d", "by": "b", "what": "w", "source": "s",
                             "rejudge": {"verdict": "false", "findings": [
                                 {"slug": "paper-a", "report": "audit", "index": "x"}]}}]}
    with pytest.raises(tool.CorpusError, match="index is a number"):
        tool.measure(with_ledger(corpus, ledger), "new")


def test_a_verdict_written_as_a_json_boolean_is_counted(corpus: Path) -> None:
    path = corpus / "report" / "judged" / "field.json"
    verdicts = json.loads(path.read_text("utf-8"))
    for entry in verdicts:
        entry["verdict"] = {"true": True, "false": False}.get(entry["verdict"], entry["verdict"])
    path.write_text(json.dumps(verdicts))
    result = tool.measure(corpus, "new", ledger=False)
    assert len(result["findings"]) == 9 and result["skipped"] == {"verdict unclear": 1}

