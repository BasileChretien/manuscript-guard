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
from dataclasses import replace
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
        "raw-block", "vocabulary-conflict", "unreadable", "code-block-unread", "script-not-read",
        "identifier-not-sent", "output-not-read", "baseline-tables-not-read",
    ), f"what a reader could not read, or the settings disagree on: {_LATER}"),
    **dict.fromkeys((
        "first-reads-unreadable", "held-out-read-elsewhere", "code-block-text-number",
        "not-read-in-latex", "gate-errored", "causal-words-not-read",
    ), f"what a gate could not read, or a gate that raised: {_LATER}"),
    **dict.fromkeys(("authors-not-looked-for", "document-person", "comment-not-matched",
                     "named"), f"an editor's or a referee's note on the documents: {_LATER}"),
    **dict.fromkeys((
        "caption-names-another", "cited-out-of-order", "display-not-cited",
        "pointer-form-unread", "pointer-to-nothing", "pointer-word-mismatch",
    ), f"a pointer to a table or a figure, matched by its label: {_LATER}"),
    **dict.fromkeys((
        "comparison-contradicted", "unit-differs-from-emitted", "interval-level-differs",
        "interval-level-undeclared", "spread-label-differs", "data-date-not-declared",
        "dataset-date-english",
    ), f"what stands beside a binding, against what the analysis emitted: {_LATER}"),
    **dict.fromkeys((
        "parameter-unread", "prose-as-value", "unplaced-table", "unquoted-result",
        "unused-literature", "count-below-minimum", "baseline-p-values",
        "declared-same-but-differs", "declared-same-but-displayed-differently",
        "family-uncorrected", "interpretation-sentences", "interval-excludes-estimate",
        "p-against-interval", "ratio-interval-asymmetric", "related-id-repeated",
        "same-as-unresolved",
    ), f"of the results and the literature the analysis emitted, not of a sentence: {_LATER}"),
    **dict.fromkeys((
        "count-recoverable", "binary-not-possible", "binary-unfound", "sd-not-possible",
        "mean-not-assessable", "whole-numbers-unfound", "flow-broken", "flow-note",
    ), f"of a table's rows, a flow or a flag's label, whose context is the row: {_LATER}"),
    **dict.fromkeys((
        "cited-not-listed", "cited-written", "would-ask", "self-citation-author",
        "self-citation-journal", "self-citation-not-counted", "self-citation-read",
        "quotation-unpaired",
    ), f"a referee's or an editor's list, said once for the run: {_LATER}"),
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
                  "value-splits-paragraph", "malformed-placeholder", "typed-parameter",
                  "threshold-undeclared", "interval-reversed", "interval-not-quoted-whole",
                  "quoted-alone", "bound-dangling", "bound-duplicated", "bound-uncheckable",
                  "interval-inverted", "estimate-outside-interval", "reply-unbound-number",
                  "manuscript-empty", "summary-claim-stronger", "summary-not-reported"),
    "G7": ("entry-never-cited", "citation-beyond-list", "title-not-searchable"),
    "arithmetic": ("does-not-fit", "not-found"),
    "abstract": ("abstract-not-found", "abstract-rounded", "abstract-conflict",
                 "question-only-in", "question-background"),
    "notices": ("not-audited", "headings-read", "passed-over", "nothing-read",
                "abstract-not-compared", "question-no-abstract", "question-no-results"),
    "compare": ("version-read", "version-pdf", "file-read",
                "fact-changed", "fact-gone", "fact-new", "section-same", "section-changed",
                "section-new", "section-gone", "section-moved"),
    # Keyed by the figure's file and the way of seeing, and by the refused file and the
    # kind of refusal (Basile, 2026-11-21, "Stable key first": their messages change).
    "G3": ("figure-colours-confused", "figure-greyscale-confused"),
    "BUILD": ("tex-refused",),
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


def test_the_key_scheme_is_numbered_and_raised_past_the_first() -> None:
    """The corpus tool reads the scheme from each run's commit; #709 changed the part of
    Word and PDF papers on purpose, and raised it from 1 (Basile, 2026-11-20); G3's colours
    and BUILD's refusals named their subject, and raised it from 2 (2026-11-21)."""
    assert isinstance(keys.SCHEME, int) and not isinstance(keys.SCHEME, bool)
    assert keys.SCHEME >= 3


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


def test_the_fallback_leaves_out_the_findings_own_path_whole_a_space_in_it_too() -> None:
    """A project in a folder whose name holds a space: the path the finding names is taken
    out whole, and every folder above it, before any other absolute path is looked for
    (round 1 of #706: "Jane Doe" kept "Doe" and the rest of the path in the digest)."""
    slash = chr(92)
    spaced = Path(slash.join(("C:", "Users", "Jane Doe", "paper", "results")))
    plain = Path(slash.join(("D:", "w", "paper", "results")))
    here, there = (Finding("G1", "no-results", f"no results fragments in {folder}",
                           path=folder).key for folder in (spaced, plain))  # fmt: skip
    assert here == there
    folder = Path("/home/Jane Doe/paper")
    said = Finding("G0", "authors-incomplete", f"{folder} has no authors.yaml",
                   path=folder / "authors.yaml").key  # fmt: skip
    assert said == Finding("G0", "authors-incomplete", "/srv/p has no authors.yaml",
                           path=Path("/srv/p/authors.yaml")).key  # fmt: skip


def test_a_folder_above_the_findings_path_is_left_out_only_where_it_stands_whole() -> None:
    """The finding's path, and each folder above it, is taken out of a message only where it
    stands whole, not inside another path (round 2 of #706: the path `/data/raw.csv` was cut
    out of `analysis/data/raw.csv`, which then read as `analysis`)."""
    path = Path("/data/raw.csv")
    inside = Finding("G1", "input-missing", "analysis/data/raw.csv is not read", path=path)
    other = Finding("G1", "input-missing", "analysis is not read", path=path)
    assert inside.key != other.key
    assert inside.key == Finding("G1", "input-missing", "analysis/data/raw.csv is not read",
                                 path=Path("/w/raw.csv")).key  # fmt: skip
    whole = Finding("G1", "input-missing", "'/data/raw.csv' is not read", path=path)
    assert whole.key == Finding("G1", "input-missing", "'/w/raw.csv' is not read",
                                path=Path("/w/raw.csv")).key  # fmt: skip


def test_the_tools_own_folder_is_left_out_of_a_key_from_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A message that names the tool's own file, as a gate that raised does, keys alike from
    two builds of the tool in two folders, as the corpus runs each commit from its own: the
    folders' names hold a space, which `_ABSOLUTE` alone would stop at (scoped check of #706:
    with plain names the test passed without `_INSTALLED`)."""

    def keyed(installed: bool) -> set[str]:
        said = set()
        for build in ("/corpus/my builds/aaa111", "/corpus/my builds/bbb222"):
            folder = keys.paths_of(f"{build}/src/manuscript_guard") if installed else ()
            monkeypatch.setattr(keys, "_INSTALLED", folder)
            said.add(Finding("G2", "gate-errored", "G2 could not run: KeyError in "
                             f"{build}/src/manuscript_guard/gates/numbers.py line 9").key)
        return said

    assert len(keyed(installed=True)) == 1
    assert len(keyed(installed=False)) == 2


#: Tables of a paper audited with `--whole-numbers Age` and `--non-negative Weight`: the same
#: rows in two tables of other headers, and a share written in a sentence that does not fit.
TABLES = """# Results

Of the patients, 12 of 40 (35%) were women, and the rest were men.

Table 1. Characteristics of group A.

| Characteristic | Group A (n = 10) |
|---|---|
| Age, mean (SD) | 3.47 (1.20) |
| Weight, mean (SD) | 2.0 (3.0) |

Table 2. Characteristics of cohort B.

| Characteristic | Cohort B (n = 10) |
|---|---|
| Age, mean (SD) | 3.47 (1.20) |
| Weight, mean (SD) | 2.0 (3.0) |
"""


def test_a_share_in_a_sentence_and_a_mean_in_a_table_are_keyed(tmp_path: Path) -> None:
    """The share a sentence writes beside its counts, by the share as typed and its sentence
    (scoped check of #706: it fell back); a GRIM mean by the mean and its n, and a skewed
    mean by the cell, each in its row with its table's header row, so that one row in two
    tables of other headers is two keys."""
    found = _json("audit", str(a_paper(tmp_path, TABLES)), "--json", "--whole-numbers", "Age",
                  "--non-negative", "Weight")["findings"]  # fmt: skip
    arithmetic = [one for one in found if one["section"] == "Arithmetic"]
    assert arithmetic and [one["key"] for one in arithmetic if one.get("key_from")] == []
    fits = keyed(found, "does-not-fit")
    assert [key for key in fits if "|12of40(35%)|" in key] != []
    grim = [key for key in fits if "|3.47/n=10@" in key]
    skewed = keyed(found, "mean-sd-skewed")
    assert len(grim) == len(set(grim)) == 2, grim
    assert len(skewed) == len(set(skewed)) == 2, skewed
    assert all(key.split("|")[2] == "2.0(3.0)" for key in skewed)


def test_a_written_share_keys_alike_with_the_abstract_compared_or_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A share a sentence writes is digested in the text as read, not in the text with the
    compared Abstract blanked, as the other numbers are (second scoped check of #706). In a
    Word paper the Abstract's heading is a line alone, which `abstract.where` takes for the
    Abstract's and the blanking took away; under "Patients and methods", a heading no line
    alone marks, the share's part rests on that line alone (the follow-up's review)."""
    from test_audit_claims import make_docx

    from manuscript_guard.auditing import abstract

    paper = make_docx(tmp_path / "paper.docx", [
        ("Abstract", True), ("Of 40 patients, 12 were women.", False),
        ("Patients and methods", True),
        ("Of the patients, 12 of 40 (35%) were women, and the rest were men.", False),
        ("Results", True), ("The rate was 4.7 in all.", False)])  # fmt: skip

    def share() -> list[str]:
        return [key for key in keyed(audited(paper), "does-not-fit") if "|12of40(35%)|" in key]

    compared = share()
    monkeypatch.setattr(abstract, "where", lambda piece, line: "")
    assert compared and share() == compared


def test_a_mean_under_a_header_that_spans_columns_names_each_row_of_it(tmp_path: Path) -> None:
    """The column a GRIM mean is keyed by is named by every header cell over it, each the
    one whose span covers it, down to the row that names its n: 3.47 under Treatment's men,
    Treatment's women and Control's men is three keys, none numbered and none with an empty
    column (the follow-up's review)."""
    from test_audit import make_docx, para, row

    def spanning(text: str) -> str:
        return (f"<w:tc><w:tcPr><w:gridSpan w:val='2'/></w:tcPr><w:p><w:r><w:t>{text}</w:t>"
                "</w:r></w:p></w:tc>")

    header = ("<w:tr><w:tc><w:p><w:r><w:t>Characteristic</w:t></w:r></w:p></w:tc>"
              + spanning("Treatment") + spanning("Control") + "</w:tr>")
    table = ("<w:tbl>" + header + row("", "Men (n = 10)", "Women (n = 10)", "Men (n = 10)",
                                       "Women (n = 10)")
             + row("Age, mean (SD)", "3.47 (1.20)", "3.47 (0.90)", "3.47 (1.10)", "5.00 (1.00)")
             + "</w:tbl>")  # fmt: skip
    paper = make_docx(tmp_path / "paper.docx", para("Results") + para("Table 1.") + table)
    found = _json("audit", str(paper), "--json", "--whole-numbers", "Age")["findings"]
    grim = [key.split("|")[2] for key in keyed(found, "does-not-fit") if "3.47/n=10" in key]
    assert sorted(grim) == ["3.47/n=10@control/men(n=10)", "3.47/n=10@treatment/men(n=10)",
                            "3.47/n=10@treatment/women(n=10)"], grim  # fmt: skip


def _grim(paper: Path, label: str) -> list[str]:
    found = _json("audit", str(paper), "--json", "--whole-numbers", label)["findings"]
    return [key.split("|")[2] for key in keyed(found, "does-not-fit") if "/n=" in key]


def test_a_mean_is_named_by_the_header_rows_under_its_n_too(tmp_path: Path) -> None:
    """Below the row that names the n, a header row that holds no mean names the column as
    well: "Treatment (n = 20)" over Baseline and Week 12 is two keys, neither numbered
    (round 1 of #709)."""
    from test_audit import make_docx, para, row

    spanning = ("<w:tc><w:tcPr><w:gridSpan w:val='2'/></w:tcPr><w:p><w:r><w:t>Treatment "
                "(n = 20)</w:t></w:r></w:p></w:tc>")  # fmt: skip
    table = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Characteristic</w:t></w:r></w:p></w:tc>"
             + spanning + "</w:tr>" + row("", "Baseline", "Week 12")
             + row("Age, mean (SD)", "3.47 (1.20)", "3.47 (0.90)") + "</w:tbl>")  # fmt: skip
    found = _grim(make_docx(tmp_path / "paper.docx", para("Results") + para("Table 1.") + table),
                  "Age")  # fmt: skip
    assert sorted(found) == ["3.47/n=20@treatment(n=20)/baseline",
                             "3.47/n=20@treatment(n=20)/week12"], found  # fmt: skip


def test_a_one_line_tabular_still_names_its_column(tmp_path: Path) -> None:
    """A LaTeX tabular typed on one line has its header and its rows on one source line:
    the header row is still read (round 1 of #709: the column was empty)."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\\begin{document}\\section{Results}\n"
                     "\\begin{tabular}{lc} Characteristic & Men (n = 10) \\\\ Age, mean (SD) "
                     "& 3.47 (1.20) \\\\ \\end{tabular}\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    assert _grim(paper, "Age") == ["3.47/n=10@men(n=10)"]


def test_a_row_of_means_above_names_no_column(tmp_path: Path) -> None:
    """A row of means above a mean, one of which names its n, "3.1 (1.0), n = 25", is a row
    of the table, not of its header: editing 3.1 leaves the key of 3.47 below it as it was
    (round 1 of #709)."""
    text = ("# Results\n\nTable 1. Scores.\n\n| Score | Group A |\n|---|---|\n"
            "| Score A, mean (SD) | {x} (1.0), n = 25 |\n| Score B, mean (SD) | 3.47 (1.20) |\n")
    found = [_grim(a_paper(tmp_path, text.replace("{x}", x), f"{x}.md"), "Score")
             for x in ("3.1", "3.2")]  # fmt: skip
    assert found[0] == found[1] == ["3.47/n=25@groupa"], found


def test_a_row_of_data_above_ends_the_header(tmp_path: Path) -> None:
    """A mean's column is named by the header rows alone: the first row of data, here a
    median [IQR] and a count n (%), ends them, so editing a datum above leaves the key of
    3.47 as it was (round 2 of #709: "45 [30-60]" joined it)."""
    text = ("# Results\n\nTable 1. Scores.\n\n| Characteristic | Treatment (n = 20) |\n"
            "|---|---|\n| Age, median [IQR] | {x} [30-60] |\n| Female, n (%) | 12 (60.0%) |\n"
            "| Score, mean (SD) | 3.47 (1.20) |\n")  # fmt: skip
    found = [_grim(a_paper(tmp_path, text.replace("{x}", x), f"{x}.md"), "Score")
             for x in ("45", "46")]  # fmt: skip
    assert found[0] == found[1] == ["3.47/n=20@treatment(n=20)"], found


def test_a_row_of_data_ends_the_header_however_its_datum_is_written(tmp_path: Path) -> None:
    """A row of data ends the header whatever its first datum opens on, its emphasis aside:
    an en dash for its minus, a bracket, a comparison, or nothing reported, "NR" or a dash
    alone. Editing it leaves the key of 3.47 below as it was (the scoped check of #709)."""
    rows = [("| Change, mean (SD) | {x} (1.2) |", "\u20130.5", "\u20130.6"),
            ("| Age, median [IQR] | **{x}** [30-60] |", "45", "46"),
            ("| P value | <{x} |", "0.001", "0.002"),
            ("| Dose | {x} |", "NR", "\u2013")]  # fmt: skip
    for at, (row, one, other) in enumerate(rows):
        text = ("# Results\n\nTable 1. Scores.\n\n| Characteristic | Treatment (n = 20) |\n"
                f"|---|---|\n{row}\n| Score, mean (SD) | 3.47 (1.20) |\n")  # fmt: skip
        found = [_grim(a_paper(tmp_path, text.replace("{x}", x), f"{at}-{x}.md"), "Score")
                 for x in (one, other)]  # fmt: skip
        assert found[0] == found[1] == ["3.47/n=20@treatment(n=20)"], (row, found)


def test_a_header_row_with_no_label_names_the_column(tmp_path: Path) -> None:
    """A row whose first cell is empty is a header's however its cells open: the doses
    under "Drug (n = 20)" name the two columns of 3.47, two keys and no ordinal (the scoped
    check of #709: "10 mg" read as data ended the header)."""
    from test_audit import make_docx, para, row

    spanning = ("<w:tc><w:tcPr><w:gridSpan w:val='2'/></w:tcPr><w:p><w:r><w:t>Drug (n = 20)"
                "</w:t></w:r></w:p></w:tc>")  # fmt: skip
    table = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Characteristic</w:t></w:r></w:p></w:tc>"
             + spanning + "</w:tr>" + row("", "10 mg", "20 mg")
             + row("Age, mean (SD)", "3.47 (1.20)", "3.47 (0.90)") + "</w:tbl>")  # fmt: skip
    found = _grim(make_docx(tmp_path / "paper.docx", para("Results") + para("Table 1.") + table),
                  "Age")  # fmt: skip
    assert sorted(found) == ["3.47/n=20@drug(n=20)/10mg", "3.47/n=20@drug(n=20)/20mg"], found


def test_two_columns_of_one_n_give_a_mean_two_keys(tmp_path: Path) -> None:
    """A GRIM mean is keyed by its column too: one row's 3.47 under two columns of n = 10
    is two findings and two keys, neither numbered."""
    text = ("# Results\n\nTable 1. Characteristics.\n\n"
            "| Characteristic | Men (n = 10) | Women (n = 10) |\n|---|---|---|\n"
            "| Age, mean (SD) | 3.47 (1.20) | 3.47 (0.90) |\n")  # fmt: skip
    found = _json("audit", str(a_paper(tmp_path, text)), "--json", "--whole-numbers",
                  "Age")["findings"]  # fmt: skip
    grim = [key for key in keyed(found, "does-not-fit") if "3.47/n=10" in key]
    assert len(grim) == len(set(grim)) == 2, grim
    assert not any("#" in key.split("|")[2] for key in grim)


def test_a_note_on_the_pdfs_of_a_folder_given_names_its_subject(tmp_path: Path) -> None:
    """Audited as a folder, a paper beside a PDF: the note that the PDF was not read keys on
    what it is about, as every note on the inputs does (round 2 of #706: it fell back)."""
    folder = tmp_path / "given"
    folder.mkdir()
    (folder / "paper.md").write_text("# Results\n\nThe rate was 4.7 in all.\n", encoding="utf-8")
    (folder / "figure.pdf").write_bytes(b"%PDF-1.4 not read\n")
    found = audited(folder)
    assert "audit|passed-over|pdfs in the folder given|-" in keyed(found, "passed-over")
    notes = [one for one in found if one["section"] == "Inputs"]
    assert notes and [one["key"] for one in notes if one.get("key_from")] == []


def test_a_rewrap_that_begins_a_line_with_a_block_sign_cuts_its_sentence() -> None:
    """The splitter frozen for keys takes a line that begins with what opens a block for a
    new block, as decided: a re-wrap there moves the key, and a re-wrap anywhere else in the
    same sentence does not (DESIGN.md, Known gaps)."""
    for whole, before in (("It was significant (P > 0.05) in men.", "> 0.05)"),
                          ("The cohort began in March 2012. It ended later.", "2012. ")):
        cut = whole.replace(" " + before, "\n" + before, 1)
        elsewhere = whole.replace(" ", "\n", 1)
        assert keys.placed(cut, 3) != keys.placed(whole, 3), cut
        assert keys.placed(elsewhere, 3) == keys.placed(whole, 3), elsewhere


def test_identical_sentences_of_one_part_number_their_findings_together() -> None:
    """Two identical sentences of one part have one digest: the findings on one subject in
    both are numbered as one sentence's, by their offsets, so a finding added in the first
    moves the key of the one in the second (DESIGN.md, Known gaps)."""
    first, second = (Keyed("G2", "unclassified-number", "2.37", "abc", at) for at in (10, 500))
    assert keys.assign([first, second]) == [
        "G2|unclassified-number|2.37#1|abc", "G2|unclassified-number|2.37#2|abc"]
    added = Keyed("G2", "unclassified-number", "2.37", "abc", 12)
    assert keys.assign([first, added, second])[2] == "G2|unclassified-number|2.37#3|abc"
    assert keys.assign([second]) == ["G2|unclassified-number|2.37|abc"]


def test_a_replys_bindings_and_numbers_are_keyed_in_its_sentence() -> None:
    """The response letter's unresolved binding and unbound number name what they are about
    and the sentence they stand in (round 1 of #706: they fell back)."""
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import reply_numbers

    text = "We now give {{results.gone}} in Table 2. The rate was 4.7 in all.\n"
    found = reply_numbers(text, Path("reply.md"), "R1.1", Classifier.load(), {}).findings
    said = {one.code: one.as_dict() for one in found}
    assert set(said) == {"unresolved-binding", "reply-unbound-number"}
    assert all("key_from" not in one for one in said.values())
    assert said["unresolved-binding"]["key"].split("|")[2] == "results.gone"
    assert said["reply-unbound-number"]["key"].split("|")[2] == "4.7"
    assert said["unresolved-binding"]["key"].split("|")[3] != said[
        "reply-unbound-number"]["key"].split("|")[3]


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
    assert keyed(found, "not-audited") == ["audit|not-audited|paper.md reference list 1|-"]
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


def test_compare_tells_two_sections_of_one_title_apart_by_the_one_above(tmp_path: Path) -> None:
    text = ("# Methods\n\nWords here.\n\n## Sensitivity\n\nOne way.\n\n# Results\n\n"
            "More words.\n\n## Sensitivity\n\nAnother way.\n")  # fmt: skip
    found = compared(a_paper(tmp_path, text, "v1.md"),
                     a_paper(tmp_path, text.replace("Another", "A third"), "v2.md"))
    subjects = [key.split("|")[2] for key in keyed(found, "section-same")
                + keyed(found, "section-changed")]  # fmt: skip
    assert {"methods/sensitivity", "results/sensitivity"} <= set(subjects), subjects


def test_each_use_of_a_citation_beyond_the_list_is_keyed_in_its_sentence(tmp_path: Path) -> None:
    text = ("# Results\n\nIt rose [5]. It fell later [5].\n\n# References\n\n"
            "1. Smith J. A paper. J Test. 2020;1:1-2.\n")  # fmt: skip
    found = keyed(audited(a_paper(tmp_path, text)), "citation-beyond-list")
    assert len(found) == 2 and len(set(found)) == 2, found


def _colour_keys(root: Path) -> dict[str, str]:
    """The key of each finding G3 makes of a project's figures' colours, by its message."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.figure_colours import check_figure_colours

    return {found.message: found.key
            for found in check_figure_colours(load_project(root)[0]).findings}  # fmt: skip


def test_a_figures_confused_colours_keep_their_key_when_the_pairs_listed_change(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G3's finding on one way of seeing lists the pairs it confuses: one pair more, as
    another rule for comparing them gives (#715 stops pairing white), is the same finding
    with the same key, named by the figure's file from the project's root and the way
    (Basile, 2026-11-21, "Stable key first")."""
    from test_corruption import _GREEN, _RED, _painted

    from manuscript_guard.gates import figure_colours

    _painted(project, _RED, _GREEN)
    (before,) = _colour_keys(project).items()
    assert before[1] == "G3|figure-colours-confused|figures/forest.svg@deuteranopia|-"
    found = figure_colours.confusions
    monkeypatch.setattr(figure_colours, "confusions", lambda colours, *rest: [
        *(said := found(colours, *rest)), *(replace(one, first="#123456") for one in said)])
    (after,) = _colour_keys(project).items()
    assert after[0] != before[0] and "#123456" in after[0]
    assert after[1] == before[1]


def test_each_way_of_seeing_a_figure_is_its_own_key_in_any_folder(
    project: Path, tmp_path: Path,
) -> None:
    """Colours one figure confuses in two ways, with deuteranopia and in grey, are two
    findings and two keys; the same project in another folder gives the same keys."""
    import shutil

    from test_corruption import _GREEN, _ORANGE, _RED, _SKY, _painted

    _painted(project, _RED, _GREEN, _ORANGE, _SKY)
    found = _colour_keys(project)
    subjects = sorted(key.split("|")[2] for key in found.values())
    assert "figures/forest.svg@deuteranopia" in subjects
    assert "figures/forest.svg@greyscale" in subjects
    assert len(subjects) == len(set(subjects)) == len(found)
    moved = shutil.copytree(project, tmp_path / "elsewhere" / "paper")
    assert sorted(_colour_keys(moved).values()) == sorted(found.values())


def test_two_figures_of_one_name_outside_the_project_are_two_keys(project: Path) -> None:
    """Figures placed from outside the project, `../shared/a/fig.svg` and `../shared/b/fig.svg`,
    each with its sidecar, are keyed by the path that climbs out to them, never an absolute
    one: two keys, not one of the file's name (round 1 of #720)."""
    from test_corruption import _GREEN, _RED

    lines = "".join(f'<path d="M0 {10 * n}L90 {10 * n}" style="fill: none; stroke: {colour}"/>'
                    for n, colour in enumerate((_RED, _GREEN)))  # fmt: skip
    for folder in ("a", "b"):
        shared = project.parent / "shared" / folder
        shared.mkdir(parents=True)
        (shared / "fig.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100pt" height="80pt" '
            f'viewBox="0 0 100 80">{lines}</svg>', encoding="utf-8")
        (shared / "fig.guard.yaml").write_text("schema: manuscript-guard/figure-guard/1\n",
                                               encoding="utf-8")  # fmt: skip
    main = project / MAIN
    main.write_text(main.read_text(encoding="utf-8") + "\n![One](../shared/a/fig.svg)\n\n"
                    "![Two](../shared/b/fig.svg)\n", encoding="utf-8")  # fmt: skip
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.figure_colours import check_figure_colours

    found = check_figure_colours(load_project(project)[0]).findings
    subjects = sorted(one.key.split("|")[2] for one in found if "fig.svg" in one.key)
    assert subjects == ["../shared/a/fig.svg@deuteranopia",
                        "../shared/b/fig.svg@deuteranopia"], subjects  # fmt: skip


def _refusals(root: Path) -> dict[str, str]:
    """The message of each `tex-refused` BUILD gives a project, by its key as `--json` says
    it, numbered where two share one."""
    from manuscript_guard.build.latex_check import check_latex
    from manuscript_guard.contracts import load_project

    said = json.loads(check_latex(load_project(root)[0]).to_json())["findings"]
    return {found["key"]: found["message"] for found in said if found["code"] == "tex-refused"}


def test_a_latex_refusal_keeps_its_key_when_its_message_changes(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal is keyed by its file and its kind, with the line it stands on: reworded or
    lengthened, as #716 lengthens one, it keeps its key. Two inputs of one kind on two lines
    are two keys, and two on one line two numbered keys (Basile, 2026-11-21)."""
    from test_corruption import _as_latex

    from manuscript_guard.text.latex import commands

    entry = _as_latex(project)
    entry.write_text("\\documentclass{article}\n\\begin{document}\n\\input{gone}\n"
                     "\\input{lost} \\input{missing}\n\\includepdf{x.pdf}\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    before = _refusals(project)
    subjects = sorted(key.split("|")[2] for key in before)
    assert subjects == ["manuscript/main.tex@command", "manuscript/main.tex@input-not-followed",
                        "manuscript/main.tex@input-not-followed#1",
                        "manuscript/main.tex@input-not-followed#2"], subjects  # fmt: skip
    assert len({key.split("|")[3] for key in before}) == 3
    monkeypatch.setitem(commands.REFUSED, "includepdf", "reworded, and said at greater length")
    after = _refusals(project)
    assert set(after) == set(before)
    assert [after[key] for key in after if "@command" in key] != [
        before[key] for key in before if "@command" in key]


_PREAMBLE, _BODY, _END = "\\documentclass{article}\n", "\\begin{document}\n", "\n\\end{document}\n"
#: For each kind of `tex-refused`, a manuscript's `main.tex` the reader refuses with it, and
#: the other files of the manuscript.
REFUSED_KINDS = {
    "command": (_PREAMBLE + _BODY + "\\includepdf{x.pdf}" + _END, {}),
    "redefined": (_PREAMBLE + "\\renewcommand{\\section}[1]{\\textbf{#1}}\n" + _BODY
                  + "\\section{Results}" + _END, {}),
    "defined-again": (_PREAMBLE + _BODY + "\\renewcommand{\\section}[1]{x}" + _END, {}),
    "unknown-citation": (_PREAMBLE + _BODY + "As shown \\mycitep{key}." + _END, {}),
    "citation-note": (_PREAMBLE + "\\usepackage{biblatex}\n" + _BODY + "\\cites(" + "a" * 400
                      + _END, {}),
    "delimiter-missing": (_PREAMBLE + "\\def\\eg/{e.g.}\n" + _BODY + "We \\eg here." + _END, {}),
    "definition-body": (_PREAMBLE + "\\def\\foo#1" + "a" * 400 + "\n" + _BODY + "x" + _END, {}),
    "binding-in-siunitx": (_PREAMBLE + "\\usepackage{siunitx}\n" + _BODY
                           + "\\qty{\\mg{results.x}}{kg}" + _END, {}),
    "binding-as-typed": (_PREAMBLE + _BODY + "\\verb|\\mg{results.x}|" + _END, {}),
    "starred-import": (_PREAMBLE + "\\usepackage{import}\n" + _BODY + "\\import*{a/}{b}" + _END,
                       {}),
    "environment": (_PREAMBLE + _BODY + "\\begin{minted}{python}\nx\n\\end{minted}" + _END, {}),
    "encoding": (_PREAMBLE + "\\usepackage[latin1]{inputenc}\n" + _BODY + "Caf\u00e9." + _END, {}),
    # Declared in a file of ASCII, refused by the tree where another file is not.
    "encoding/tree": (_PREAMBLE + "\\usepackage[latin1]{inputenc}\n" + _BODY + "\\input{a}"
                      + _END, {"a.tex": "Caf\u00e9.\n"}),
    "makeatletter": (_PREAMBLE + _BODY + "\\makeatletter\nx\n\\makeatother\nOne." + _END, {}),
    "conditional": (_PREAMBLE + _BODY + "\\ifx a b\nx\n\\fi\nOne." + _END, {}),
    "input-not-followed": (_PREAMBLE + _BODY + "\\input{gone}" + _END, {}),
    "input-cycle": (_PREAMBLE + _BODY + "\\input{main}" + _END, {}),
}  # fmt: skip


@pytest.mark.parametrize("kind", sorted(REFUSED_KINDS))
def test_each_kind_of_refusal_is_its_own_subject(tmp_path: Path, kind: str) -> None:
    """Each place the reader refuses with `tex-refused` gives its finding the subject of its
    own kind, `manuscript/main.tex@<kind>`: a kind named wrong, or two swapped, fails here."""
    root = tmp_path / "paper"
    init_project(root, "A study of reports")
    for path in (root / "manuscript").rglob("*.md"):
        path.unlink()
    main_tex, others = REFUSED_KINDS[kind]
    (root / "manuscript" / "main.tex").write_text(main_tex, encoding="utf-8")
    for name, text in others.items():
        (root / "manuscript" / name).write_text(text, encoding="utf-8")
    subjects = {key.split("|")[2] for key in _refusals(root)}
    assert subjects == {f"manuscript/main.tex@{kind.split('/')[0]}"}, subjects


def test_every_tex_refused_the_reader_makes_names_its_kind() -> None:
    """Each place the LaTeX reader refuses with `tex-refused` names the kind its key takes:
    one with none would key on the code, and two kinds of refusal on one line would share a
    key. Each kind named is one `REFUSED_KINDS` gives an input for."""
    import ast

    from manuscript_guard.text.latex import mask

    folder = Path(mask.__file__).parent
    unnamed, named = [], set()
    for name in ("mask.py", "structure.py"):
        tree = ast.parse((folder / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", getattr(node.func, "id", None))
            first = node.args[0] if node.args else None
            refused = isinstance(first, ast.Constant) and first.value == "tex-refused"
            kind = next((one.value for one in node.keywords if one.arg == "kind"), None)
            if called == "_refuse" and refused and kind is None and len(node.args) > 3:
                kind = node.args[3]
            if called in ("_refuse", "Refusal") and refused and not (
                    isinstance(kind, ast.Name) or (isinstance(kind, ast.Constant) and kind.value)):
                unnamed.append(f"{name}:{node.lineno}")
            if called == "_skip_block" and not any(one.arg == "kind" for one in node.keywords):
                unnamed.append(f"{name}:{node.lineno}")
            if called in ("_refuse", "Refusal", "_skip_block") and isinstance(kind, ast.Constant):
                named.add(kind.value)
    assert unnamed == [], unnamed
    assert named == {kind.split("/")[0] for kind in REFUSED_KINDS}, named


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
