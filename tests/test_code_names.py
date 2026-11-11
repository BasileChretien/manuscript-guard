"""G14's fifth reading: no name from the code in the prose (`gates/code_names.py`).

A results key, a data dictionary's variable or a word written with underscores, standing in
a sentence, is a name the reader has never seen. The reading must find each of the three,
give the dictionary's label for a variable, and read a key or a variable in a code span; and
it must leave alone what is not prose (a binding, a citation key, a URL, a path, maths), a
key or a variable that is a word of the prose (`sex`, `eGFR`) and a word the paper keeps.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.findings import FAIL, WARN
from manuscript_guard.gates import check_language
from manuscript_guard.gates.code_names import CODE, Names, Prose, code_shaped, judge_code_names
from manuscript_guard.gates.language import _file
from manuscript_guard.policy import DRAFTING, SUBMISSION

MAIN = Path("manuscript") / "main.md"
OPEN = "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
CLOSE = "\\end{document}\n"


def read(text: str, *, keys=(), labels=None, kept=(), stage=None):
    """The findings of the reading on one Markdown file."""
    file = _file(0, MAIN, text, [], False)
    prose = Prose(file.path, file.text, file.printed, file.code, file.line_of)
    names = Names(frozenset(keys), dict(labels or {}), frozenset(kept))
    return judge_code_names([prose], names, stage).findings


def named(text: str, **given) -> list[str]:
    """The names the reading reports in `text`, in the order it reports them."""
    return [f.message.split("'")[1] for f in read(text, **given)]


# ---------------------------------------------------------------- what is found


def test_a_word_with_underscores_is_found_once_where_it_first_stands() -> None:
    text = "# Results\n\nThe estimate was high.\n\nThe hr_adj_main rose, and hr_adj_main held.\n"
    (finding,) = read(text)
    assert finding.code == CODE and finding.severity == WARN
    assert finding.line == 5
    assert finding.message == (
        "'hr_adj_main' is written with underscores, the way a name in code is written, and the "
        "reader has never seen it: it is used 2 times, first in the prose"
    )
    assert "code_names_kept" in finding.hint


def test_it_fails_at_submission_and_warns_before() -> None:
    text = "Patients with ckd_flag were older.\n"
    assert [f.severity for f in read(text, stage=DRAFTING)] == [WARN]
    assert [f.severity for f in read(text, stage=SUBMISSION)] == [FAIL]


def test_a_dictionary_variable_is_named_with_its_label() -> None:
    (finding,) = read("Patients with ckd_flag were older.\n",
                      labels={"ckd_flag": "Chronic kidney disease"})  # fmt: skip
    assert finding.message.startswith(
        "'ckd_flag' is the name of a variable in the data dictionary, which labels it "
        "'Chronic kidney disease'"
    )
    assert finding.hint.startswith("write what it is, as the label says: 'Chronic kidney disease'")


def test_a_results_key_is_found_bare_and_as_its_binding_names_it() -> None:
    text = "The ror.point was 3.2, and results.case.n_cases were counted.\n"
    findings = read(text, keys={"ror.point", "case.n_cases"})
    assert [f.message.split("'")[1] for f in findings] == ["ror.point", "results.case.n_cases"]
    assert all("is a key of the results" in f.message for f in findings)
    assert "`{{results.case.n_cases}}`" in findings[1].hint


@pytest.mark.parametrize(
    ("name", "shaped"),
    [("age_group", True), ("age.group", True), ("ckdFlag", True), ("hrAdjMain", True),
     ("sex", False), ("BMI", False), ("eGFR", False), ("CD4", False), ("visit1", False),
     ("mRNA", False), ("lncRNA", False), ("HbA1c", False), ("nCases", False)],
)  # fmt: skip
def test_a_key_or_a_variable_is_read_only_where_it_is_shaped_as_code(
    name: str, shaped: bool
) -> None:
    """The example's dictionary has `sex`, `drug` and `year`: words of every sentence."""
    assert code_shaped(name) is shaped
    found = named(f"The {name} was recorded.\n", labels={name: "A label"}, keys={name})
    assert found == ([name] if shaped else [])


def test_a_key_or_a_variable_in_a_code_span_is_found_and_a_function_is_not() -> None:
    text = "Grouped by `age_group` and `ror.point`, tabulated with `tbl_summary`.\n"
    findings = read(text, keys={"ror.point"}, labels={"age_group": "Age group"})
    assert [f.message.split("'")[1] for f in findings] == ["age_group", "ror.point"]
    assert all(f.message.endswith("first in a code span") for f in findings)


def test_a_variable_in_code_is_read_by_its_name_and_a_file_of_it_is_not() -> None:
    labels = {"age_group": "Age group"}
    assert named("Read `df$age_group` and `df.age_group`.\n", labels=labels) == ["age_group"]
    assert named("Read `data/age_group.csv` and `age_group.csv`.\n", labels=labels) == []


def test_an_escaped_underscore_is_the_underscore_it_prints() -> None:
    assert named("The hr\\_adj\\_main rose.\n") == ["hr_adj_main"]


def test_italics_and_double_underscores() -> None:
    assert named("The _hr_adj_ rose, the taxon g__Bacteroides fell.\n") == [
        "hr_adj", "g__Bacteroides"
    ]  # fmt: skip
    assert named("The __init__ method and __bold__ text.\n") == []


def test_a_word_with_no_letter_is_no_name() -> None:
    assert named("Between 2020_2024 and 1_000 reports.\n") == []


def test_a_subscript_typed_as_code_is_found() -> None:
    """pandoc prints the underscore, so `C_max` is wrong in the paper either way."""
    assert named("The C_max was reached at 2 hours.\n") == ["C_max"]


# ---------------------------------------------------------------- what is not prose


@pytest.mark.parametrize(
    "text",
    [
        "The rate was {{results.case.n_cases}} in all.",
        "As reported [@smith_2019; @jones_et_al].",
        "See https://example.org/a_b/c_d and <https://example.org/e_f>.",
        "See [the data](data/raw_reports.csv).",
        "Run analysis/01_simulate.py on data\\raw_reports.",
        "Written to raw_reports.csv and fit_model.R.",
        "Write to first_last@example.org.",
        "The term $x_i + \\beta_{age}$ is fitted.",
        "Kept. <!-- hr_adj_main to check -->",
        "```python\nhr_adj_main = fit()\n```",
        '::: {custom-style="Body_Text"}\nPlain words.\n:::',
        'Some <span class="a_b">words</span>.',
        "Words \\label{sec:age_group} here.",
        "A table, see @tbl:n_cases.",
        "A note.[^note_one]\n\n[^note_one]: The note.",
        "---\ntitle: The hr_adj_main paper\n---\n\nPlain words.",
        "Plain words.\n\n![The hr_adj_main curve](figure.png)",
        "Files are in raw_hr_adj\\2024.",
        "See [the portal][data_portal].\n\n[data_portal]: https://example.org",
    ],
)
def test_what_is_not_prose_is_not_read(text: str) -> None:
    assert named(text + "\n") == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        # pandoc drops `\study` and `\raw` as TeX commands and prints "C:_hr_adj".
        ("Files are in C:\\study\\raw_hr_adj.", ["hr_adj"]),
        # Round 2: a tag or a TeX command against a name made its run a path's.
        ("The <u>age_group</u> was used.", ["age_group"]),
        ('<span style="color:red">age_group</span> was used.', ["age_group"]),
        ("The age_group<sup>a</sup> was used.", ["age_group"]),
        ("The age_group\\textsuperscript{a} value.", ["age_group"]),
        # A label no definition has is printed as typed; one that has is not, in any case.
        ("See [the portal][data_portal] here.", ["data_portal"]),
        ("See [the portal][Data_Portal] here.\n\n[data_portal]: https://example.org", []),
        # Round 3: a definition under the reference list, and a case pandoc does not fold.
        ("See [the portal][data_portal].\n\n# References\n\n[data_portal]: https://e.org", []),
        ("[x][straße_id] and more.\n\n[strasse_id]: https://example.org", ["straße_id"]),
        # pandoc reads this line as a definition and prints nothing of it.
        ("[Note]: the hr_adj values are shown.", []),
    ],
)
def test_what_pandoc_prints_is_read(text: str, found: list[str]) -> None:
    """Each case checked against what `pandoc -t plain` prints (3.9.0.2)."""
    assert named(text + "\n", labels={"age_group": "Age group"}) == found


def test_the_reference_list_is_not_read() -> None:
    text = "Plain words.\n\n# References\n\nSmith J. The ckd_flag paper. 2019.\n"
    assert named(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Plain words.\n\n![Risk by `age_group` and `ror.point`](figure.png)\n",
        "Plain words.\n\n# References\n\nSmith J. The `age_group` and `ror.point` paper.\n",
    ],
)
def test_a_key_or_a_variable_in_code_is_not_read_where_the_prose_is_not(text: str) -> None:
    """Round 1: the code spans were read in an image's caption and in the reference list,
    where G14 reads no sentence."""
    assert named(text, keys={"ror.point"}, labels={"age_group": "Age group"}) == []


def test_a_word_kept_is_not_read_in_the_prose_or_in_code() -> None:
    text = "The g__Bacteroides genus and `age_group` and age_group.\n"
    kept = {"g__Bacteroides", "age_group"}
    assert named(text, labels={"age_group": "Age group"}, kept=kept) == []


# ---------------------------------------------------------------- the manuscript


def written(project: Path, text: str, *, supplement: str | None = None, stage=None, **paper):
    """`check_language` on exactly this main text, with the example's results and dictionary,
    `paper` set in paper.yaml."""
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    if supplement is not None:
        folder = project / "manuscript" / "supplementary"
        folder.mkdir()
        (folder / "S1.md").write_text(supplement, encoding="utf-8")
    _set(project, **paper)
    return check_language(load_project(project)[0], stage)


def _set(project: Path, **paper) -> None:
    if not paper:
        return
    path = project / "paper.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.setdefault("language", {}).update(paper)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def coded(report) -> list[tuple[str, str]]:
    return [(f.path.name, f.message) for f in report.findings if f.code == CODE]


def test_the_example_prints_no_name_from_its_code(project: Path) -> None:
    assert coded(check_language(load_project(project)[0], SUBMISSION)) == []


def test_the_example_s_dictionary_and_results_are_read(project: Path) -> None:
    report = written(project, "# Results\n\nBy age_group, the ror.point rose.\n")
    assert coded(report) == [
        ("main.md", "'age_group' is the name of a variable in the data dictionary, which "
                    "labels it 'Age group', and the reader has never seen it: it is used "
                    "once, first in the prose"),
        ("main.md", "'ror.point' is a key of the results the analysis wrote, and the reader "
                    "has never seen it: it is used once, first in the prose"),
    ]  # fmt: skip


def test_the_supplement_is_read(project: Path) -> None:
    report = written(project, "# Results\n\nPlain words.\n",
                     supplement="# Supplementary methods\n\nThe hr_adj_main model.\n")  # fmt: skip
    assert [name for name, _message in coded(report)] == ["S1.md"]


def test_a_kept_word_in_paper_yaml_is_not_read(project: Path) -> None:
    report = written(project, "# Results\n\nThe g__Bacteroides genus.\n",
                     code_names_kept=["g__Bacteroides"])  # fmt: skip
    assert coded(report) == []


def test_a_kept_word_with_a_space_is_refused_by_the_schema(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    written(project, "# Results\n\nPlain words.\n", code_names_kept=["two words"])
    report, _project, _chosen, _deferred = _run_gates(project, stage=DRAFTING)
    assert any(f.code == "schema-violation" and "code_names_kept" in f.message
               for f in report.failures)  # fmt: skip


def test_check_fails_at_submission_on_a_code_name(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    path.write_text(text.replace(old, old + " The hr_adj_main model held."), encoding="utf-8")
    drafted, _p, _c, _d = _run_gates(project, stage=DRAFTING)
    assert drafted.ok and any(f.code == CODE for f in drafted.findings)
    # The edit makes the panel's reading stale too, which fails at submission as well.
    submitted, _p, _c, _d = _run_gates(project, stage=SUBMISSION)
    assert CODE in {f.code for f in submitted.failures}


def _latex(project: Path, text: str):
    folder = project / "manuscript"
    shutil.rmtree(folder)
    folder.mkdir()
    (folder / "main.tex").write_text(text, encoding="utf-8")
    return check_language(load_project(project)[0])


def test_a_latex_manuscript_is_read(project: Path) -> None:
    report = _latex(project, OPEN + (
        "The hr\\_adj\\_main rose by \\texttt{age\\_group}, see \\verb|tbl_summary| and "
        "\\cite{smith_2019}, $x_i$ and \\mg{results.ror.point}.\n"
    ) + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == [
        "hr_adj_main", "age_group"
    ]  # fmt: skip
    (variable,) = (f for f in report.findings if "age_group" in f.message)
    assert variable.line == 4 and variable.message.endswith("first in a code span")


def test_a_latex_figure_s_caption_and_reference_list_are_not_read_in_code(project: Path) -> None:
    """Round 1: `\\texttt` in a figure's caption, in the preamble's title and in
    `thebibliography` was read, where G14 reads no word."""
    report = _latex(project, (
        "\\documentclass{article}\n\\title{The \\texttt{age\\_group} study}\n"
        "\\begin{document}\n\\section{Results}\nPlain words.\n"
        "\\begin{figure}\\caption{By \\texttt{age\\_group}}\\end{figure}\n"
        "\\begin{thebibliography}{1}\n\\bibitem{a} The \\texttt{age\\_group} paper.\n"
        "\\end{thebibliography}\n"
    ) + CLOSE)  # fmt: skip
    assert coded(report) == []
