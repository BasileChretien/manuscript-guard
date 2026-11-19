"""The key `--json` gives each finding (`keys`, Basile, 2026-11-19): `gate|code|subject|digest`.

A run of the tool is paired with another by these keys, so what is held here is what makes a
key stable: it does not move when a message is reworded, a line moves or a paragraph is
re-wrapped, and it moves when the finding is about something else, stands in another
sentence or in another part of the paper. Each family of codes names its own subject, and a
code that names none falls back on its context, which only the codes listed in
`ON_THE_FALLBACK` may.
"""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from generated import INPUTS, generated
from hypothesis import given

from manuscript_guard import keys
from manuscript_guard.cli import main
from manuscript_guard.findings import Finding, Report
from manuscript_guard.keys import Keyed
from manuscript_guard.scaffold import init_project

MAIN = Path("manuscript") / "main.md"

#: A paper with something for each family the audit and `check` key: numbers that do not
#: fit, two of them equal in one sentence, an interval its estimate is outside, a phrase G6
#: reads, a short form never defined and one used before it is, two spellings, a name from
#: code and a reference entry nothing cites.
PAPER = """# Abstract

The hazard ratio was 1.50 (95% CI 1.60 to 2.10). Mortality was 12.5% in the cohort.

# Methods

We used OR and t tests. The tests gave t(29) = 2.05, P = 0.30 and t(29) = 2.05, P = 0.30 in
the two groups. The odds ratio (OR) was read later.

# Results

The hazard ratio was 1.50 (95% CI 1.60 to 2.10) [1]. It is important to note that
the risk was low. Mortality was 12.4% in the cohort. HR was low. We analyse
and we analyze, colour and color, and p_value here. OR rose.

# References

1. Smith J. A paper. J Test. 2020;1:1-2.
2. Jones K. Another. J Test. 2021;2:3-4.
"""

#: The codes whose findings may name no subject, and key on their context (`keys`), each
#: with why. None of them is of a family this pull request keyed (`FAMILIES`).
_LATER = "outside the families keyed first (Basile, 2026-11-19); a later pull request keys it"
ON_THE_FALLBACK = {
    **dict.fromkeys((
        "figure-review-finding", "journal-manual-unsigned", "round-not-blinded",
        "review-superseded", "similar-undecided", "plan-complete", "plan-section-empty",
        "no-review", "no-journal-chosen", "journal-profile-missing", "authors-incomplete",
        "no-results", "schema-violation", "project-exemption", "synthetic-input-quoted",
    ), f"of the project's records, the panel, the plan, the journal, the authors: {_LATER}"),
    **dict.fromkeys((
        "value-from-abstract", "statements-without-passage", "reference-unchecked",
        "citation-unresolved", "pinning-unchecked",
    ), f"of the literature's records and of Zotero: {_LATER}"),
    **dict.fromkeys((
        "front-matter-abstract", "front-matter-unreadable", "two-titles", "tex-in-the-text",
        "tex-not-judged", "rule-opens-a-block", "unclear-fence", "pointers-unchecked",
        "malformed-placeholder", "raw-block", "vocabulary-conflict", "unreadable",
        "code-block-unread", "script-not-read",
    ), f"what a reader could not read, or the settings disagree on: {_LATER}"),
    **dict.fromkeys(("sum-off", "over-header-n", "entries-not-told-apart"),
                    f"of a table's row or a whole list, whose context is the row: {_LATER}"),
    **dict.fromkeys((
        "table-same", "table-changed", "table-new", "table-gone", "table-not-read",
        "figure-same", "figure-changed", "figure-new", "figure-gone", "displays-not-compared",
        "tables-read-as-prose", "version-not-numbered", "claim-stronger", "claim-weaker",
        "claim-moved", "claim-negation",
    ), f"compare's tables, figures and claims, matched by label and by sentence: {_LATER}"),
}  # fmt: skip

#: Codes of each family keyed here, which never fall back.
FAMILIES = {
    "G14": ("abbreviation-undefined", "abbreviation-used-before-defined",
            "abbreviation-unused", "abbreviation-redefined"),
    "spelling": ("spelling-variant", "spelling-mixed", "spelling-not-as-declared"),
    "notation": ("notation-p-symbol", "notation-sign-spacing", "notation-interval",
                 "notation-percent", "notation-unit", "notation-space-missing"),
    "code names": ("code-name-in-prose",),
    "G6": ("ai-phrasing", "ai-cadence", "model-artefact", "revision-residue",
           "vague-attribution"),
    "G2 and G8": ("unclassified-number", "hand-authored-table", "unresolved-binding",
                  "summary-claim-stronger"),
    "G7": ("entry-never-cited", "citation-beyond-list", "title-not-searchable"),
    "arithmetic": ("does-not-fit", "not-found"),
    "abstract": ("abstract-not-found", "abstract-rounded", "abstract-conflict",
                 "question-only-in", "question-background"),
    "notices": ("not-audited", "headings-read", "passed-over", "nothing-read",
                "abstract-not-compared", "question-no-abstract", "question-no-results"),
    "compare": ("version-read", "version-pdf", "file-read",
                "fact-changed", "fact-gone", "fact-new", "section-same", "section-changed",
                "section-new", "section-gone", "section-moved"),
}  # fmt: skip
KEYED = frozenset(code for codes in FAMILIES.values() for code in codes)


# ---------------------------------------------------------------------------- running


def _json(*args: str) -> dict:
    """What a command prints with `--json`; no finding where it printed nothing, as `check`
    does of a `paper.yaml` it cannot read."""
    printed = StringIO()
    with redirect_stdout(printed), redirect_stderr(StringIO()):
        main(list(args))
    return json.loads(printed.getvalue()) if printed.getvalue().strip() else {"findings": []}


def checked(root: Path, stage: str = "design") -> list[dict]:
    return _json("check", str(root), "--json", "--stage", stage)["findings"]


def audited(paper: Path) -> list[dict]:
    return _json("audit", str(paper), "--json")["findings"]


def compared(old: Path, new: Path) -> list[dict]:
    return _json("compare", str(old), str(new), "--json")["findings"]


def a_project(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "paper"
    init_project(root, "A study of reports")
    (root / MAIN).write_text(text, encoding="utf-8", newline="")
    return root


def a_paper(tmp_path: Path, text: str, name: str = "paper.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")
    return path


def keyed(found: list[dict], code: str) -> list[str]:
    return [one["key"] for one in found if one["code"] == code]


def every_key(found: list[dict]) -> set[str]:
    """Each key of `found` and of each entry a finding lists."""
    return {one["key"] for one in found} | {
        form["key"] for one in found for form in one.get("forms", ())}  # fmt: skip


def fallen_back(found: list[dict]) -> set[str]:
    return {one["code"] for one in found if one.get("key_from") == keys.FROM_CONTEXT}


# ---------------------------------------------------------------- the parts of a key


def test_a_sentence_is_read_the_same_wrapped_or_not_and_however_it_is_typed() -> None:
    """The digest's normal form: one minus, one quotation mark of each kind, no spaces, no
    emphasis, no soft hyphen, a line's hyphen joined, in any case."""
    one = keys.digest(keys.MAIN, "The *odds* ratio was −0.5 “so”.")
    assert one == keys.digest(keys.MAIN, "the odds\n  ratio  was -0.5 \"so\".")
    assert keys.digest(keys.MAIN, "signifi-\ncant") == keys.digest(keys.MAIN, "significant")
    assert keys.digest(keys.MAIN, "signi­ficant") == keys.digest(keys.MAIN, "significant")
    assert one != keys.digest(keys.ABSTRACT, "The *odds* ratio was −0.5 “so”.")
    assert one != keys.digest(keys.MAIN, "The odds ratio was 0.5 “so”.")
    assert len(one) == 12 and int(one, 16) >= 0


def test_a_statistic_is_one_subject_however_it_is_spaced_and_signed() -> None:
    assert keys.statistic("t(29) = 2.05") == keys.statistic("t(29)=2.05") == "t(29)=2.05"
    assert keys.statistic("−0.5") == keys.statistic("-0.5")
    assert keys.statistic("0·5") == keys.statistic("0.5")
    assert keys.statistic("2.05") != keys.statistic("2.06")


def test_the_part_is_the_abstract_under_its_heading_and_the_supplement_by_its_file() -> None:
    text = "# Abstract\n\nOne. Two.\n\n# Methods\n\nThree.\n\nABSTRACT\n\nFour.\n"
    assert keys.part_of(text, text.index("Two")) == keys.ABSTRACT
    assert keys.part_of(text, text.index("Three")) == keys.MAIN
    assert keys.part_of(text, text.index("Four")) == keys.ABSTRACT
    assert keys.part_of(text, text.index("Three"), supplementary=True) == keys.SUPPLEMENT
    tex = "\\begin{abstract}One.\\end{abstract}\\section{Methods}Two."
    assert keys.part_of(tex, tex.index("One")) == keys.ABSTRACT
    assert keys.part_of(tex, tex.index("Two")) == keys.MAIN
    assert keys.in_supplement(Path("p/manuscript/supplementary/S1.md"))
    assert not keys.in_supplement(Path("supplementary/manuscript/main.md"))


def test_the_frozen_splitter_cuts_where_the_gates_splitter_cuts_today() -> None:
    """The copy kept for keys cuts a Markdown text where `claims.sentence_spans` does; a
    change to the gates' splitter leaves the copy, and so every key, as it is."""
    from manuscript_guard import claims

    text = "# Results\n\nOne was 2.5 (e.g. here). Two followed!\n\n- Three\n- Four is it?\n"
    theirs = {start for start, _first, _end in claims.sentence_spans(text)}
    for start in theirs:
        assert keys.sentence_at(text, start).strip() == keys.sentence_at(text, start + 1).strip()
    assert keys.sentence_at(text, text.index("Two")).startswith("Two followed!")


def test_a_note_on_the_inputs_is_a_string_that_knows_its_file() -> None:
    """A note of the audit's Inputs is made where it is read, with the file it is about,
    and stays a string, copied or not."""
    import copy

    from manuscript_guard.auditing.report import _notice

    said = keys.Notice("paper.pdf: its lines were placed in no section", "paper.pdf")
    assert said == "paper.pdf: its lines were placed in no section"
    assert copy.deepcopy(said).subject == "paper.pdf"
    assert _notice("not-audited", said).as_dict()["key"] == "audit|not-audited|paper.pdf|-"


def test_a_reworded_message_keeps_the_key_and_another_subject_moves_it() -> None:
    one = Finding("G2", "unclassified-number", "'2.37' is not bound", subject="2.37",
                  sentence="abc", context="was 2.37 in")  # fmt: skip
    reworded = Finding("G2", "unclassified-number", "2.37 has no source", subject="2.37",
                       sentence="abc", context="it was 2.37")  # fmt: skip
    other = Finding("G2", "unclassified-number", "'2.37' is not bound", subject="2.38",
                    sentence="abc")  # fmt: skip
    assert one.key == reworded.key == "G2|unclassified-number|2.37|abc"
    assert other.key != one.key
    assert one == reworded or one.message != reworded.message  # equality is as it was
    assert "key_from" not in one.as_dict() and "subject" not in one.as_dict()


def test_a_finding_with_no_subject_falls_back_on_its_context_and_says_so() -> None:
    """And on its message where it has no context, any absolute path in it left out: the
    folder of one run is no part of what the finding is (`check` of one project in two
    folders gave two keys)."""
    said = Finding("G9", "made-up", "a message", context="the context").as_dict()
    assert said["key_from"] == "context" and said["key"].startswith("G9|made-up|~")
    assert said["key"].endswith("|-")
    here, there = (Finding("G0", "no-results", f"no results fragments in {folder}").key
                   for folder in ("C:\\Temp\\mg-1\\paper\\results", "/tmp/mg-2/paper/results"))
    assert here == there
    assert here != Finding("G0", "no-results", "no figures in /tmp/mg-2/paper/results").key


def test_two_equal_subjects_in_one_sentence_are_numbered_by_offset_and_never_across() -> None:
    """`t(29) = 2.05` twice in one sentence are `#1` and `#2`, by offset whatever the order
    they are given in; the same in another sentence is no third."""
    found = [Keyed("audit", "does-not-fit", "t(29)=2.05", "aaa", 40),
             Keyed("audit", "does-not-fit", "t(29)=2.05", "aaa", 10),
             Keyed("audit", "does-not-fit", "t(29)=2.05", "bbb", 90),
             Keyed("G14", "spelling-variant", "color", None, 5),
             Keyed("G14", "spelling-variant", "color", None, 9)]  # fmt: skip
    assert keys.assign(found) == [
        "audit|does-not-fit|t(29)=2.05#2|aaa", "audit|does-not-fit|t(29)=2.05#1|aaa",
        "audit|does-not-fit|t(29)=2.05|bbb",
        "G14|spelling-variant|color|-", "G14|spelling-variant|color|-",
    ]  # fmt: skip


# ----------------------------------------------------------------- each family's subject


@pytest.fixture(scope="module")
def paper_audited(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    return audited(a_paper(tmp_path_factory.mktemp("audit"), PAPER))


def test_the_audit_keys_each_family_by_its_subject(paper_audited: list[dict]) -> None:
    found = paper_audited
    (asked,) = [one for one in found if one["code"] == "abbreviation-undefined"]
    assert asked["key"] == "G14|abbreviation-undefined|-|-"
    assert {form["key"] for form in asked["forms"]} >= {
        "G14|abbreviation-undefined|HR@main|-", "G14|abbreviation-undefined|CI@abstract|-"}
    assert keyed(found, "abbreviation-used-before-defined") == [
        "G14|abbreviation-used-before-defined|OR@main|-"]
    assert sorted(keyed(found, "spelling-variant")) == [
        "G14|spelling-variant|analyze|-", "G14|spelling-variant|color|-"]
    (names,) = [one for one in found if one["code"] == "code-name-in-prose"]
    assert names["key"] == "G14|code-name-in-prose|-|-"
    assert [form["key"] for form in names["forms"]] == ["G14|code-name-in-prose|p_value|-"]
    (phrase,) = keyed(found, "ai-phrasing")
    assert phrase.startswith("G6|ai-phrasing|important-to-note: it is important to note|")
    tests = sorted(key for key in keyed(found, "does-not-fit") if "t(29)" in key)
    assert [key.rsplit("|", 2)[1] for key in tests] == [
        "t(29)=2.05,p=0.30#1", "t(29)=2.05,p=0.30#2"]
    assert len({key.rsplit("|", 1)[1] for key in tests}) == 1  # one sentence
    outside = [key for key in keyed(found, "does-not-fit") if "/outside|" in key]
    assert len(outside) == 2 and len(set(outside)) == 2  # the abstract's and the Results'
    assert keyed(found, "abstract-not-found")[0].startswith("audit|abstract-not-found|12.5%|")
    assert keyed(found, "entry-never-cited") == ["G7|entry-never-cited|entry 2|-"]
    assert keyed(found, "not-audited") == ["audit|not-audited|paper.md reference list|-"]
    assert not fallen_back(found) - set(ON_THE_FALLBACK)


def test_check_keys_g2_by_the_number_and_its_sentence(tmp_path: Path) -> None:
    root = a_project(tmp_path, "# Results\n\nThe values were 2.37 and 2.37 here. Then 2.37.\n")
    found = keyed(checked(root), "unclassified-number")
    assert [key.split("|")[2] for key in found] == ["2.37#1", "2.37#2", "2.37"]
    assert len({key.split("|")[3] for key in found}) == 2


#: Notation of each kind written two ways.
NOTATION = """# Results

The interval was 1 to 2 (95% CI 1.1 to 2.2), and (95% CI 3.1-4.2), and (95% CI 5.1-6.2).
P < 0.05 and P<0.05 and P<0.01 here. The rate was 5 % and 6% and 7%. It took 30min.
"""


def test_check_keys_notation_by_its_form_never_by_its_words(tmp_path: Path) -> None:
    """A notation finding names the form that is not the paper's own, never the words it was
    found in, and no sentence: one finding for the paper whichever use is first."""
    found = checked(a_project(tmp_path, NOTATION))
    assert keyed(found, "notation-interval") == ["G14|notation-interval|'to'|-"]
    assert keyed(found, "notation-sign-spacing") == ["G14|notation-sign-spacing|spaced|-"]
    assert keyed(found, "notation-percent") == ["G14|notation-percent|spaced|-"]
    assert keyed(found, "notation-unit") == ["G14|notation-unit|number-unit|-"]
    moved = checked(a_project(tmp_path / "moved", NOTATION.replace("P < 0.05 and ", "")))
    assert keyed(moved, "notation-sign-spacing") == []
    assert keyed(moved, "notation-interval") == keyed(found, "notation-interval")


def test_check_keys_g8_by_the_keys_its_summary_sentence_binds(project: Path) -> None:
    """G8's claim names the keys its summary sentence binds, and the sentence."""
    main = project / MAIN
    text = main.read_text(encoding="utf-8")
    abstract = "example-drug. The reporting odds ratio was {{results.ror.point}}"
    results = "Reporting of hepatic injury was disproportionate for example-drug, with a"
    text = text.replace(abstract, "example-drug. Example-drug increased these reports: the "
                        "reporting odds ratio was {{results.ror.point}}", 1)  # fmt: skip
    text = text.replace(results, "Example-drug was associated with reports of hepatic injury, "
                        "with a", 1)  # fmt: skip
    main.write_text(text, encoding="utf-8")
    found = checked(project)
    (claim,) = keyed(found, "summary-claim-stronger")
    assert claim.split("|")[2] == "ror.ci_high+ror.ci_low+ror.point"
    assert claim.split("|")[3] != "-"
    assert not {one["code"] for one in found if one.get("key_from")} & KEYED


def test_check_and_the_audit_key_g6_and_g14_alike_on_the_same_text(tmp_path: Path) -> None:
    """The audit runs G6 and G14 as `check` does, on the same text: each finding has the
    same key in both, and each entry of a list the key of its warning in `check`."""
    text = PAPER.split("# References")[0]
    root = a_project(tmp_path, text)
    mine = [one for one in checked(root) if one["gate"] in ("G6", "G14")]
    theirs = [one for one in audited(root / MAIN) if one["gate"] in ("G6", "G14")]
    # `check` says each name from the code apart; the audit lists them, as one.
    assert every_key(mine) == every_key(theirs) - {"G14|code-name-in-prose|-|-"}
    assert "G14|code-name-in-prose|p_value|-" in every_key(mine)


def test_compare_keys_facts_and_sections(tmp_path: Path) -> None:
    old = a_paper(tmp_path, "# Results\n\nThe rate was 12.5 in all. It rose to 3.\n\n"
                  "# Gone\n\nWords.\n", "v1.md")  # fmt: skip
    new = a_paper(tmp_path, "# Results\n\nThe rate was 12.6 in all. It rose to 3.\n\n"
                  "Then 7 more.\n", "v2.md")  # fmt: skip
    found = compared(old, new)
    (changed,) = keyed(found, "fact-changed")
    assert changed.split("|")[2] == "12.5→12.6" and changed.split("|")[3] != "-"
    assert keyed(found, "fact-new") == ["compare|fact-new|7|-"]
    assert "compare|section-gone|gone|-" in keyed(found, "section-gone")
    assert keyed(found, "section-changed") == ["compare|section-changed|results|-"]


# --------------------------------------------------------------------- what moves a key


def test_a_moved_line_and_a_rewrapped_paragraph_keep_every_placed_key(tmp_path: Path) -> None:
    before = audited(a_paper(tmp_path, PAPER, "one.md"))
    moved = PAPER.replace("# Methods\n\n", "# Methods\n\nA new paragraph of words came first.\n\n")
    rewrapped = moved.replace("in\nthe two groups", "in the\ntwo groups").replace(
        "that\nthe risk", "that the\nrisk")  # fmt: skip
    after = audited(a_paper(tmp_path, rewrapped, "two.md"))
    unnamed = {key.replace("one.md", "paper") for key in every_key(before)}
    assert unnamed == {key.replace("two.md", "paper") for key in every_key(after)}


def test_another_sentence_and_another_part_move_a_placed_key(tmp_path: Path) -> None:
    edited = PAPER.replace("in\nthe two groups.", "in the groups.")
    before, after = (audited(a_paper(tmp_path, text, name))
                     for text, name in ((PAPER, "a.md"), (edited, "b.md")))  # fmt: skip
    tests = [{key for key in keyed(found, "does-not-fit") if "t(29)" in key}
             for found in (before, after)]  # fmt: skip
    assert tests[0] and tests[1] and not tests[0] & tests[1]
    # The same sentence of the Abstract and of the Results: two digests.
    outside = [key.split("|")[3] for key in keyed(before, "does-not-fit") if "/outside" in key]
    assert len(set(outside)) == 2


# ---------------------------------------------------------------- what falls back


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory, built_example: Path) -> list[dict]:
    """Every finding of `check` on the example, of the audit of its manuscript and of
    `PAPER`, and of a comparison of the two."""
    import shutil

    folder = tmp_path_factory.mktemp("runs")
    root = folder / "paper"
    shutil.copytree(built_example, root)
    paper = a_paper(folder, PAPER)
    return [*checked(root), *audited(root / MAIN), *audited(paper),
            *compared(root / MAIN, paper)]


def test_only_the_codes_listed_fall_back_on_their_context(runs: list[dict]) -> None:
    """A code of a family keyed here never falls back, and a code that does is listed with
    why: a new code with no subject fails here until it names one or is listed."""
    assert not fallen_back(runs) - set(ON_THE_FALLBACK), fallen_back(runs) - set(ON_THE_FALLBACK)
    assert not fallen_back(runs) & KEYED
    assert not set(ON_THE_FALLBACK) & KEYED
    assert all(reason.split() for reason in ON_THE_FALLBACK.values())


@generated(4)
@given(INPUTS["check"])
def test_on_generated_manuscripts_only_the_codes_listed_fall_back(given_: dict) -> None:
    """`check` of a new project with a generated manuscript and settings, at a stage, and
    the audit of the same text: the inputs the `check` reading is compared on."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mg-keys-") as folder:
        root = a_project(Path(folder), given_["text"])
        with (root / "paper.yaml").open("a", encoding="utf-8", newline="") as paper:
            paper.write(given_.get("settings", ""))
        found = checked(root, given_["stage"]) + audited(a_paper(Path(folder), given_["text"]))
    unlisted = fallen_back(found) - set(ON_THE_FALLBACK)
    assert not unlisted, unlisted
    assert not fallen_back(found) & KEYED


# ---------------------------------------------------------------- many in one report


def test_a_report_says_every_key_and_numbers_equal_ones_in_a_sentence() -> None:
    one = Finding("G2", "unclassified-number", "a", subject="2.37", sentence="abc", at=4)
    two = Finding("G2", "unclassified-number", "b", subject="2.37", sentence="abc", at=9)
    said = json.loads(Report((two, one)).to_json())["findings"]
    assert sorted(found["key"] for found in said) == [
        "G2|unclassified-number|2.37#1|abc", "G2|unclassified-number|2.37#2|abc"]
    assert keys.shared(said) == []
