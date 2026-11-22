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
    prose = Prose(file.path, file.text, file.printed, file.code, file.line_of, file.tables,
                  file.headings)
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


def test_a_name_spelt_otherwise_loses_its_hint(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14 reads a name from the code by its shape, and
    a key or a variable by its spelling", its fourth point): a key is matched whole, bare or
    after `results.`, so one with a part changed or a table's key is read only as a word
    with underscores, without the key's hint, and a variable only in the dictionary's case,
    so `Age_group` opening a sentence goes without its label."""
    underscored = "is written with underscores, the way a name in code is written"
    keys = {"case.n_cases", "ror.point"}
    (whole,) = read("The case.n_cases rose.\n", keys=keys)
    assert whole.message.startswith("'case.n_cases' is a key of the results")
    for text in ("The case.n_case rose.\n", "The results.case.n_case rose.\n"):
        (changed,) = read(text, keys=keys)
        assert changed.message.startswith(f"'n_case' {underscored}"), text
        assert "{{results." not in changed.hint, text
    assert named("The ror.points rose.\n", keys=keys) == []
    labels = {"age_group": "Age group"}
    (variable,) = read("The age_group was recorded.\n", labels=labels)
    assert "which labels it 'Age group'" in variable.message
    (opening,) = read("Age_group was recorded.\n", labels=labels)
    assert opening.message.startswith(f"'Age_group' {underscored}")
    assert "Age group" not in opening.message + opening.hint
    report = written(project, "# Results\n\nThe two_by_two and the baseline were drawn.\n")
    assert coded(report) == [
        ("main.md", f"'two_by_two' {underscored}, and the reader has never seen it: it is "
                    "used once, first in the prose"),
    ]  # fmt: skip


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


def test_emphasis_inside_a_name_or_a_tag_hides_it() -> None:
    """A known gap (DESIGN.md, Known gaps, "G14 reads a name from the code by its shape, and
    a key or a variable by its spelling", its seventh point): `*ckd*_flag` is not read, and
    an HTML tag is read as one where `<` stands against a letter, so "a <b and c_d> e" hides
    `c_d`, which a space after the `<` leaves in the prose."""
    assert named("The *ckd*_flag was recorded.\n") == []
    assert named("The ckd_flag was recorded.\n") == ["ckd_flag"]
    assert named("a <b and c_d> e\n") == []
    assert named("a < b and c_d > e\n") == ["c_d"]


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


def test_an_unknown_latex_command_s_argument_is_prose(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14 reads a name from the code by its shape, and
    a key or a variable by its spelling", its ninth point): a `glossaries` or `acronym` key
    with an underscore, `\\gls{ckd_flag}` or `\\ac{hr_adj}`, is reported though the document
    prints the entry's text, while the key of a command the reader knows, `\\cite`, is not.
    The 2026-11-09 triage planned a fix (F19), which will change this test."""
    report = _latex(project, OPEN + (
        "The \\gls{ckd_flag} and \\ac{hr_adj} groups differed \\cite{smith_2019}.\n"
    ) + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == ["ckd_flag", "hr_adj"]


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


# ------------------------------------------------- tables, maths and identifiers (D13)
#
# The corpus run of 2026-11-12 audited 52 real preprints, and judges found 82% of a sample of
# these findings false (Basile's decision 13, 2026-11-13). Each fix below is one the reader
# can make exactly: a table's cell, maths the reader did not know for maths, an identifier.

#: A pipe table and a simple table, as pandoc writes a Word table where its cells allow; the
#: header and the body each hold a name (docx-pharm-epi-B1: `beta_exp`, `SE_exp` in a header).
MARKDOWN_TABLES = (
    "# Results\n\nThe model held.\n\n"
    "| SNP | beta_exp | SE_exp |\n|---|---|---|\n| rs1 | 0.2 | 0.1 |\n| p_out | 1 | 2 |\n\n"
    "  Name        Value\n  ---------- -------\n  CPI_ALL      0.5\n  IOP_MANU     0.8\n\n"
    "After the tables, hr_adj_main rose.\n"
)


def test_a_name_in_a_markdown_table_s_cell_is_no_name_in_the_prose() -> None:
    """A name in a cell of a pipe table or a simple table, its header or its body, is not
    read; the prose after the tables is."""
    assert named(MARKDOWN_TABLES) == ["hr_adj_main"]


def test_a_name_in_a_latex_tabular_s_cell_is_no_name_in_the_prose(project: Path) -> None:
    """tex-econ-em-A2 typed its series' mnemonics in a tabular's cells, `LIBOR\\_12mth`,
    `CPI\\_ALL`: 98 findings, all false. A tabular, a `tabularx` and a `longtable`, inside a
    float or not, are cells; the sentence after them is prose."""
    report = _latex(project, (
        "\\documentclass{article}\n\\usepackage{tabularx,longtable}\n\\begin{document}\n"
        "\\section{Results}\nThe model held.\n"
        "\\begin{table}\\caption{Series}\n\\begin{tabular}{lll}\n"
        "IOS & 0,887 & 3 \\\\\nLIBOR\\_12mth & 0,532 & 6 \\\\\n\\end{tabular}\n\\end{table}\n"
        "\\begin{tabularx}{\\linewidth}{lX}\nCPI\\_ALL & 0,513 \\\\\n\\end{tabularx}\n"
        "\\begin{longtable}{ll}\nIOP\\_MANU & 0,836 \\\\\n\\end{longtable}\n"
        "After the tables, hr\\_adj\\_main rose.\n"
    ) + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == ["hr_adj_main"]


def test_a_latex_table_s_caption_and_footnote_are_read(project: Path) -> None:
    """Only a table's cells are set aside: a `longtable`'s `\\caption`, which is prose, and a
    `\\footnote` in a tabular's cell, which LaTeX prints at the foot of the page, are read as
    they were before the cells were set aside (round 1 of #673, finding 2)."""
    report = _latex(project, OPEN + (
        "\\begin{longtable}{ll}\\caption{Loadings of hr\\_adj\\_main}\\\\\na & 1 \\\\\n"
        "CPI\\_ALL & 2 \\\\\n\\end{longtable}\n"
        "\\begin{tabular}{ll}\nIOP\\_MANU\\footnote{As age\\_band is coded.} & 1 \\\\\n"
        "\\end{tabular}\n"
    ) + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == [
        "hr_adj_main", "age_band"]


@pytest.mark.parametrize(("table", "found"), [  # round 2 of #673
    ("\\resizebox{\\linewidth}{!}{\\begin{tabular}{l}\n% a\\footnote{old\nCPI\\_ALL\\\\\n"
     "\\end{tabular}}\n", []),
    ("\\begin{longtable}{l}\\caption[Short $[a,b]$]{Long hr\\_adj}\\\\\na\\\\\\end{longtable}\n",
     ["hr_adj"]),
    ("\\begin{tabular}{l}a\\tablefootnote{The age\\_band.}\\\\\\end{tabular}\n", ["age_band"]),
])  # fmt: skip
def test_a_note_or_caption_in_a_table_is_read_where_it_prints(project: Path, table, found) -> None:
    report = _latex(project, OPEN + table + CLOSE)
    assert [message.split("'")[1] for _name, message in coded(report)] == found


def test_a_markdown_table_s_caption_is_read() -> None:
    """A pipe table's caption, pandoc's `Table:` line before it or after it, is prose."""
    text = ("# Results\n\nTable: Loadings of hr_adj_main\n\n| Series | n |\n|---|---|\n"
            "| CPI_ALL | 2 |\n\n: Loadings by age_band\n")  # fmt: skip
    assert named(text) == ["hr_adj_main", "age_band"]


def test_optidef_s_problems_are_maths(project: Path) -> None:
    """tex-qbio-pe-A2 set its problem in optidef's `mini!`, whose arguments and constraints
    are maths (optidef.sty sets each environment's body in an `align`); the reader took them
    for prose and read `w_{min}` as `w_min`. Each of optidef's sixteen problems is maths."""
    from manuscript_guard.text.latex.commands import MATHS

    names = ("mini", "maxi", "argmini", "argmaxi")
    for name in [f"{base}{mark}" for base in names for mark in ("", "*", "!", "e")]:
        assert name in MATHS, name
    report = _latex(project, OPEN + (
        "The window is chosen.\n"
        "\\begin{mini!}[0]\n{w}{\\sum_{t=w}^T y_t}{\\label{eqn:obj}}{}\n"
        "\\addConstraint{w_{min}\\le}{w\\le w_{max}}{}\n\\end{mini!}\n"
        "\\begin{argmaxi*}{x}{f_{low}(x)}{}{}\\end{argmaxi*}\n"
        "After it, hr\\_adj\\_main rose.\n"
    ) + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == ["hr_adj_main"]


@pytest.mark.parametrize("typed", ["RRID:SCR_006571", "RRID: SCR_006571", "RRID:SCR\\_006571"])
def test_a_name_right_after_rrid_is_a_resource_s_identifier(typed: str) -> None:
    """pdf-med-B2 named its software by RRID, `RRID:SCR_006571`: an identifier, no name from
    the code (#663 hid the accession from G14, and so from this reading)."""
    assert named(f"PsychoPy ({typed}) ran it, and hr_adj_main rose.\n") == ["hr_adj_main"]


# ------------------------------------------- machine text quoted: two exact shapes
# Basile, 2026-11-22, "Exact shapes only": a name alone in angle brackets is a placeholder,
# and a `name = value` line under a `[section]` line is a configuration's. Nothing broader:
# a boxed environment as such is read.


@pytest.mark.parametrize(
    "text",
    [
        # pandoc reads it bare as an HTML tag and prints nothing of it (3.9.0.2).
        "The placeholder <PAPER_TEXT> is replaced.",
        # as pandoc writes it from a .docx
        "The placeholder \\<PAPER_TEXT\\> is replaced.",
        "The placeholder <PAPER\\_TEXT> is replaced.",
        "The prompt ends:\n\n\\<IN_CONTEXT_EXAMPLE\\>\n\n\\<SYNTHESIS_TEXT\\>\n\nIt is sent.",
        "Placeholders (<PAPER_TEXT>, <synthesis_text>) are replaced.",
    ],
)
def test_a_name_alone_in_angle_brackets_is_a_placeholder(text: str) -> None:
    """A prompt's placeholder, `<PAPER_TEXT>`, is replaced by what the program puts there:
    no name the reader has to know. A name in the prose beside it is read."""
    assert named(text + " The hr_adj_main rose.\n") == ["hr_adj_main"]


@pytest.mark.parametrize(
    "text",
    [
        "When n < max_len > m, it stops.",
        "When n \\< max_len \\> m, it stops.",
        # a word against the escaped bracket, as pandoc writes it from a .docx (#768 round 1)
        "When n\\<max_len\\> m, it stops.",
        "The bound a<max_len held.",
        "The pair <max_len, min_len> holds.",
        "Placeholder < max_len > here.",
    ],
)
def test_a_name_beside_a_comparison_sign_is_read(text: str) -> None:
    """`<` and `>` as signs of a comparison, or a bracket that holds more than the name, are
    no placeholder: the name is read. Each case is printed as typed by `pandoc -t plain`
    (3.9.0.2); "1<max_len>2" is not, pandoc reading `<max_len>` as an HTML tag, so it is
    tried in LaTeX (`test_a_name_between_comparison_signs_in_latex_is_read`)."""
    assert "max_len" in named(text + "\n")


def test_a_name_between_comparison_signs_in_latex_is_read(project: Path) -> None:
    """In LaTeX "1<max\\_len>2" has a digit against each bracket, and "a<b\\_c> d" a word
    against the left one: comparisons, read."""
    report = _latex(project, OPEN + "When 1<max\\_len>2 and n < min\\_len > m, it stops; "
                    "so does a<b\\_c> d.\n" + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == [
        "max_len", "min_len", "b_c"]  # fmt: skip


@pytest.mark.parametrize(
    "header",
    ["[1]", "[12.3]", "**[2]**", "**\\[2\\]**"],
)
def test_a_bracketed_number_alone_on_a_line_opens_no_section(header: str) -> None:
    """A section's key starts with a letter: "[1]" alone on a line, a reference's number,
    opens no configuration, and the setting under it is read (#768 round 1)."""
    assert named(f"# Methods\n\n{header}\n\nn_total = 12\n") == ["n_total"]


def test_a_latex_line_break_with_its_space_opens_no_section(project: Path) -> None:
    """`\\\\[6pt]` alone on a line is a line break and its space, which the view does not
    print: no section, and the setting under it is read."""
    report = _latex(project, OPEN + "Line one\\\\[6pt]\n\\\\[6pt]\n\nn\\_total = 12\n" + CLOSE)
    assert [message.split("'")[1] for _name, message in coded(report)] == ["n_total"]


def test_a_heading_ends_a_quoted_value_that_runs_on() -> None:
    """A heading ends the paragraphs a quoted value runs on over, as a `[section]` line
    does: the value is then unpaired, and its line no configuration's (#768 round 1)."""
    text = ("**\\[chat\\]**\n\ngreet_text = \\\"Hello\n\n# Results\n\n"
            "The hr_adj_main rose on a screen of 24\\\"\n")  # fmt: skip
    assert named(text) == ["greet_text", "hr_adj_main"]


def test_a_setext_heading_ends_a_quoted_value_and_a_fenced_hash_does_not() -> None:
    """The headings that end a value's run are those the reading finds (`find_headings`): a
    setext heading does, and a line `# x` inside a fenced block, which is no heading, does
    not (#768 round 2)."""
    setext = ("**\\[chat\\]**\n\ngreet_text = \\\"Hello\n\nResults\n-------\n\n"
              "The hr_adj_main rose on a screen of 24\\\"\n")  # fmt: skip
    assert named(setext) == ["greet_text", "hr_adj_main"]
    fenced = ("**\\[chat\\]**\n\ngreet_text = \\\"Hello\n\n```\n# x\n```\n\nGoodbye.\\\"\n\n"
              "The hr_adj_main rose.\n")  # fmt: skip
    assert named(fenced) == ["hr_adj_main"]


def test_a_latex_heading_ends_a_quoted_value(project: Path) -> None:
    """In LaTeX a `\\section` ends a quoted value's run as a Markdown heading does: both
    names are read (#768 round 2)."""
    report = _latex(project, OPEN + "[app]\n\ngreet\\_text = \"Hello\n\n\\section{Results}\n\n"
                    "The hr\\_adj\\_main rose 24\"\n" + CLOSE)  # fmt: skip
    assert [message.split("'")[1] for _name, message in coded(report)] == [
        "greet_text", "hr_adj_main"]  # fmt: skip


def test_something_unprinted_against_the_bracket_makes_no_placeholder() -> None:
    """What the view does not print, a code span, a citation key or a binding, counts as
    standing against `<` or its escape, so the name is read: the shape as decided (DESIGN.md,
    Known gaps)."""
    assert named("Run `tool`\\<INPUT_FILE\\> now.\n") == ["INPUT_FILE"]


def test_a_key_in_a_code_span_in_a_quoted_value_is_read() -> None:
    """The machine text is set aside from the sentences only: a key of the results in a code
    span inside a configuration's quoted value is still one the reader cannot know (#768
    round 1)."""
    findings = read("# Methods\n\n[app]\n\nprompt = \"use `ckd_flag`\"\n", keys={"ckd_flag"})
    assert [(f.message.split("'")[1], f.message.endswith("first in a code span"))
            for f in findings] == [("ckd_flag", True)]  # fmt: skip


@pytest.mark.parametrize(
    "value",
    ["“fast”", "1e-3", "1_000", "{ a = 1 }", "1979-05-27", "\"fast\" # a comment"],
    ids=["curly quotes", "exponent", "underscored number", "inline table", "date",
         "comment"],
)  # fmt: skip
def test_a_value_toml_allows_and_this_reading_does_not_ends_the_configuration(
    value: str,
) -> None:
    """Values TOML allows that are none of the exact shapes end the configuration, so the
    settings after them are read: conservative (DESIGN.md, Known gaps)."""
    text = f"# Methods\n\n[app]\n\nrun_mode = {value}\n\nseen_codes = 12\n"
    assert named(text) == ["run_mode", "seen_codes"]


#: A configuration file in TOML as pandoc writes it from a .docx that holds it as
#: paragraphs, a section's header bold; a name in the sentence after it.
CONFIGURATION = (
    "# Appendix\n\n**\\[app\\]**\n\nsecret_key = \\\"secret key\\\"\n\n**\\[bot\\]**\n\n"
    "api_key = \\\"API key\\\"\n\n**\\[bot.settings\\]**\n\nmodel = \\\"gpt-4o\\\"\n\n"
    "**\\[chat\\]**\n\ninitial_message = \\\"\\_The interview will begin.\\_\\\"\n\n"
    "resume_message = \\\"\\_It resumes.\\_\\\"\n\n[study]\n\nprotocol_process = true\n\n"
    "max_turns = 12\n\nstop_words = ['end', 'stop']\n\nseen_codes = \\[\"a\", \"b\"\\]\n\n"
    "plain_text = 'kept as typed'\n\nThe hr_adj_main rose.\n"
)


def test_a_line_of_a_configuration_under_its_section_is_no_prose() -> None:
    """Each `name = value` line under a `[section]` line, with only such lines or blank ones
    between, its value quoted, a number, true or false or a bracketed list: the paper quotes
    a file, and its names are the file's. The sentence after it is read."""
    assert named(CONFIGURATION) == ["hr_adj_main"]


@pytest.mark.parametrize(
    "text",
    [
        # no section above it
        "# Methods\n\nrun_mode = \"fast\"\n",
        # a sentence between the section and the line
        "# Methods\n\n[app]\n\nThe file sets a key.\n\nrun_mode = \"fast\"\n",
        # a value that is words, not a quoted string
        "# Methods\n\n[app]\n\nrun_mode = fast and safe\n",
        # more than the line in its paragraph
        "# Methods\n\n[app]\n\nWe set run_mode = \"fast\" for all.\n",
        # a header that is no section's
        "# Methods\n\n[app] is the section.\n\nrun_mode = \"fast\"\n",
    ],
)
def test_a_line_shaped_as_a_setting_in_prose_is_read(text: str) -> None:
    """Only the exact shape: a `name = value` line with no `[section]` line above it, or
    with prose between, or a value of words, is read as prose."""
    assert named(text) == ["run_mode"]


def test_a_value_quoted_over_several_paragraphs_is_one_configuration_line() -> None:
    """A quoted value that the Word conversion broke into paragraphs runs on to the one
    that ends with its closing quote, and the configuration goes on after it (Basile,
    2026-11-22, "Quote may close later"). The sentence after it is read."""
    text = ("**\\[chat\\]**\n\ninitial_message = \\\"Hello.\\\"\n\n"
            "stop_response = \\\"Thank you. The interview is over.\n\n"
            "Please close the window.\\\"\n\nstop_text = \\\"It looks like you stopped the\n\n"
            "interview. Close it\n\nnow.\\\"\n\nstop_label = \\\"Close.\\\"\n\n"
            "**\\[study\\]**\n\nprotocol_process = true\n\nThe hr_adj_main rose.\n")  # fmt: skip
    assert named(text) == ["hr_adj_main"]


@pytest.mark.parametrize(
    ("after", "found"),
    [
        # never closed before the end of the text
        ("Please close the window.\n", ["stop_response"]),
        # never closed before the next setting
        ("Please close the window.\n\nstop_label = \\\"Close.\\\"\n\nIt ends.\\\"\n",
         ["stop_response", "stop_label"]),
        # never closed before the next section
        ("Please close.\n\n**\\[study\\]**\n\nprotocol_process = true\n\nIt ends.\\\"\n",
         ["stop_response"]),
        # a quote in a paragraph between that does not close it
        ("Say \"stop\" and close it.\\\"\n\nstop_label = \\\"Close.\\\"\n",
         ["stop_response", "stop_label"]),
    ],
    ids=["the end", "a setting", "a section", "a quote between"],
)  # fmt: skip
def test_a_quote_that_does_not_close_ends_the_configuration_where_it_opened(
    after: str, found: list[str]
) -> None:
    """The quotes must pair: a value whose quote does not close before the next `name =
    value` line, the next `[section]` line or the end of the text is no configuration line,
    and the configuration ends at it (Basile, 2026-11-22, "Quote may close later")."""
    text = ("**\\[chat\\]**\n\ninitial_message = \\\"Hello.\\\"\n\n"
            "stop_response = \\\"Thank you.\n\n" + after)  # fmt: skip
    assert named(text) == found


def test_a_quote_that_closes_later_outside_a_configuration_changes_nothing() -> None:
    """With no `[section]` line above it, a value quoted over two paragraphs is prose."""
    text = "# Methods\n\nstop_response = \\\"Thank you.\n\nPlease close it.\\\"\n"
    assert named(text) == ["stop_response"]


#: An appendix that quotes an LLM's prompt in a `tcolorbox`, its placeholders on their own
#: lines and in the sentence after it, a vocabulary term quoted in it.
PROMPT = OPEN + (
    "\\begin{tcolorbox}[title=Prompt]\n"
    "IMPORTANT:\\hspace{0.3em}Record every value.\\\\\n"
    "-- Example:\\hspace{0.3em}\"matprov:length\\_thickness\"\\\\\n"
    "<IN\\_CONTEXT\\_EXAMPLE>\\\\\n\n<PAPER\\_TEXT>\n\\end{tcolorbox}\n\n"
    "The placeholder <PAPER\\_TEXT> is dynamically replaced, and hr\\_adj\\_main rose.\n"
) + CLOSE


def test_a_latex_prompt_s_placeholders_are_not_read_and_the_box_is(project: Path) -> None:
    """In LaTeX `<PAPER\\_TEXT>` is a placeholder too, on its own line or in a sentence. The
    box is no setting-aside: the quoted vocabulary term in it, `length_thickness`, is read
    as before, and the all-caps word IMPORTANT is read as a short form, here one never
    defined (DESIGN.md, Known gaps)."""
    report = _latex(project, PROMPT)
    assert [message.split("'")[1] for _name, message in coded(report)] == [
        "length_thickness", "hr_adj_main"]  # fmt: skip
    assert [f.code for f in report.findings
            if f.code.startswith("abbreviation-") and "IMPORTANT" in f.message] == [
        "abbreviation-undefined"], report.findings  # fmt: skip
