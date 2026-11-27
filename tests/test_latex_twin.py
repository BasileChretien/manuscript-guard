"""The example's manuscript in LaTeX, `tests/data/latex/manuscript/` (DESIGN.md, "LaTeX
manuscripts", "Tests"). Run against the example's analysis, results and citation keys, it
binds the same keys under the same headings as the example, and G2 counts and judges its
numbers as it counts and judges the example's."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.gates import check_numbers
from manuscript_guard.text.latex import views
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import chain_at, heading_index

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"


@pytest.fixture
def twin(project: Path) -> Path:
    """The example project with the twin for its manuscript."""
    folder = project / "manuscript"
    shutil.rmtree(folder)
    shutil.copytree(TWIN, folder)
    return project


def _markdown_bindings(root: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    """Each binding of the example, in order, with its file's document and its headings."""
    found = []
    folder = root / "manuscript"
    for path in (folder / "main.md", *sorted((folder / "supplementary").glob("*.md"))):
        text = path.read_text(encoding="utf-8")
        index = heading_index(text)
        where = "supplement" if "supplementary" in path.parts else "main"
        found += [(where, p.ref, tuple(chain_at(index, p.start))) for p in parse(text)[0]]
    return found


def _latex_bindings(root: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    found = []
    for read in views.files(root / "manuscript"):
        where = "supplement" if read.source.path.startswith("supplementary/") else "main"
        found += [(where, p.ref, tuple(views.chain(read.source, p.start)))
                  for p in read.placeholders]  # fmt: skip
    return found


def test_the_twin_binds_the_examples_keys_in_order_under_the_same_headings(
    built_example: Path, twin: Path
) -> None:
    assert _latex_bindings(twin) == _markdown_bindings(built_example)


def _cited(root: Path) -> list[tuple[str, str, bool]]:
    """Each citation, in the order the files print them and each file writes them: its file,
    its key, and whether it is narrative."""
    from manuscript_guard.text.reader import citation_uses

    uses = citation_uses(load_project(root)[0])
    files = list(dict.fromkeys(use.path for use in uses))
    written = sorted(uses, key=lambda use: (files.index(use.path), use.start))
    return [(use.path.name, use.citekey, use.narrative) for use in written]


def test_the_twin_cites_the_examples_keys_in_order_as_the_example_does(
    built_example: Path, twin: Path
) -> None:
    """Step 5: the citations join the comparison when the citation reader does."""
    twin_cited = [(key, narrative) for _name, key, narrative in _cited(twin)]
    example = [(key, narrative) for _name, key, narrative in _cited(built_example)]
    assert twin_cited == example and example


def _numbers(root: Path):
    loaded, _ = load_project(root)
    namespace, results, literature, _ = load_namespace(loaded)
    return check_numbers(loaded, namespace, results, literature)


#: What G2 counts of a manuscript, by `Report.counts`.
_COUNTED = ("source_files", "numeric_atoms", "bindings", "atoms_term", "atoms_structural",
            "atoms_convention", "atoms_project_exempt")  # fmt: skip


def test_g2_counts_and_judges_the_twin_as_it_does_the_example(
    project: Path, built_example: Path, tmp_path: Path
) -> None:
    example = _numbers(project)
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = _numbers(root)
    assert {key: latex.counts[key] for key in _COUNTED} == {
        key: example.counts[key] for key in _COUNTED
    }
    # G2 reads the twin's pointers to tables and figures too, from step 13, and finds what it
    # finds in the example's.
    found = Counter((f.code, f.severity) for f in latex.findings)
    assert found == Counter((f.code, f.severity) for f in example.findings)


def test_g4_counts_the_twins_words_sections_and_display_items_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 6: the journal's limits, its required sections and its statements read the twin
    as Markdown would print it, and find what they find in the example."""
    from manuscript_guard.gates import check_journal

    example = check_journal(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_journal(load_project(root)[0])
    counted = ("abstract_words", "main_text_words", "display_items")
    assert {key: latex.counts[key] for key in counted} == {
        key: example.counts[key] for key in counted
    }
    assert example.counts["main_text_words"] > 0 and example.counts["display_items"] > 0
    assert Counter((f.code, f.severity) for f in latex.findings) == Counter(
        (f.code, f.severity) for f in example.findings
    )


def test_g14_reads_the_twins_words_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 7: the abbreviations, terms, spelling and notation of the twin are read as the
    example's are, a bound value in an interval or a percentage among them, and G14 says of
    it what it says of the example."""
    from manuscript_guard.gates import check_language

    example = check_language(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_language(load_project(root)[0])
    assert latex.counts == example.counts
    assert example.counts["notation_intervals"] > 0 and example.counts["notation_percents"] > 0
    # G14's question on the short forms never defined names each at its file and line,
    # main.tex's and main.md's (decision 30): held by the warnings it holds on each, and by
    # its forms.
    from manuscript_guard.auditing.undefined import unasked

    assert [(f.code, f.message) for f in unasked(list(latex.findings))] == [
        (f.code, f.message) for f in unasked(list(example.findings))
    ]
    assert [[form for form, _w in getattr(f, "forms", ())] for f in latex.findings] == [
        [form for form, _w in getattr(f, "forms", ())] for f in example.findings]


def test_g6_reads_the_twins_prose_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 7: G6 counts the twin's words, phrases, artefacts and vague attributions as the
    example's, and says of it what it says of the example."""
    from manuscript_guard.gates import check_writing

    example = check_writing(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_writing(load_project(root)[0])
    assert latex.counts == example.counts and example.counts["prose_words"] > 1000
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g8_reads_the_twins_summaries_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 8: the numbers the twin's Abstract and conclusions give are looked for where the
    paper reports, as the example's are."""
    from manuscript_guard.gates.reported import check_reported

    projekt = load_project(project)[0]
    example = check_reported(projekt, load_namespace(projekt)[1])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_reported(twin, load_namespace(twin)[1])
    assert latex.counts == example.counts
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g9_reads_the_twins_claims_and_methods_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 8: the twin's claims are the example's, word for word, so the example's lock
    holds them, and its Methods have as many paragraphs that point at no step: a heading or a
    typed table is no paragraph of them."""
    from manuscript_guard.gates.methods import anchored, check_methods

    projekt = load_project(project)[0]
    example = check_methods(projekt, *load_namespace(projekt)[:2])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_methods(twin, *load_namespace(twin)[:2])
    assert latex.counts == example.counts and example.counts["method_claims"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]
    said = [(claim.steps, claim.text) for claim in anchored(twin)[0]]
    assert said == [(claim.steps, claim.text) for claim in anchored(projekt)[0]]


def test_g15_reads_the_twins_models_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 8: the models the twin's Methods name, and the bindings it holds, are the
    example's."""
    from manuscript_guard.gates.models import check_models

    projekt = load_project(project)[0]
    example = check_models(projekt, load_namespace(projekt)[1])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_models(twin, load_namespace(twin)[1])
    assert latex.counts == example.counts and example.counts["models"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g8r_reads_the_twins_checklist_answers_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 8: the twin's claims of a guideline, and the headings the checklist's answers
    point at, are the example's."""
    from manuscript_guard.gates import check_reporting

    example = check_reporting(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_reporting(load_project(root)[0])
    assert latex.counts == example.counts
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


#: The twin's `\title`, as `main.tex` writes it.
_TWIN_TITLE = ("\\title{Reporting of hepatic injury with example-drug: a disproportionality "
               "analysis of a synthetic spontaneous reporting database}")  # fmt: skip


def _title_said(twin: Path, quote: str, stage: str = "submission") -> list[tuple[str, str, str]]:
    """What G5 says, at `stage`, of the checklist's first item answered `where: Title` with
    `quote`: each finding's code, severity and message."""
    import yaml

    from manuscript_guard.gates import check_reporting

    path = twin / "reporting" / "DEMO-OBS.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["items"][0].update(where="Title", quote=quote)
    path.write_bytes(yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode())
    found = check_reporting(load_project(twin)[0], stage=stage).findings
    return [(f.code, f.severity, f.message) for f in found if f.code.startswith("checklist-")]


def _title_answer(twin: Path, quote: str) -> list[tuple[str, str]]:
    """What G5 says, at submission, of the checklist's first item answered `where: Title`
    with `quote`: each finding's code and message."""
    return [(code, message) for code, _severity, message in _title_said(twin, quote)]


def test_a_latex_answer_in_the_title_is_held_to_the_title_main_tex_prints(twin: Path) -> None:
    """Round 1 of #813: the PDF prints `\\title{}`, not paper.yaml's title, which `init
    --latex` copies once and the author then edits in main.tex. The quote is held to the
    `\\title` as the reader prints the body, its markup and its dashes folded and its note left
    out; paper.yaml's title, which no document prints, is not found."""
    main = twin / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    assert _TWIN_TITLE in text
    main.write_bytes(text.replace(_TWIN_TITLE, (
        "\\title{Hepatic injury with \\emph{example-drug} -- a disproportionality\\\\ "
        "analysis\\thanks{Funded by no grant of any kind.} of synthetic reports}")).encode())
    assert _title_answer(twin, "Hepatic injury with example-drug \N{EN DASH} a "
                               "disproportionality analysis of synthetic reports") == []
    said = _title_answer(twin, "Reporting of hepatic injury with example-drug: a "
                               "disproportionality analysis")  # fmt: skip
    assert [code for code, _message in said] == ["checklist-quote-not-found"]
    assert "is not under the \\title in main.tex" in said[0][1]
    note = _title_answer(twin, "Funded by no grant of any kind")
    assert [code for code, _message in note] == ["checklist-quote-not-found"]


def test_the_title_read_is_the_one_tex_prints_past_a_comment_and_an_option(
    tmp_path: Path,
) -> None:
    """A `\\title` in a comment prints nothing, and a CAS template's `\\title[mode = title]`
    prints its argument; with none, there is no title to read."""
    from manuscript_guard.text.latex.printed import printed_titles

    folder = tmp_path / "manuscript"
    shutil.copytree(TWIN, folder)
    main = folder / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_bytes(text.replace(_TWIN_TITLE, (
        f"% {_TWIN_TITLE}\n\\title[mode = title]{{A title the CAS class prints}}")).encode())
    assert [(t.text, t.path, t.line) for t in printed_titles(folder)] == [
        ("A title the CAS class prints", "main.tex", 4)]
    main.write_bytes(text.replace(_TWIN_TITLE + "\n", "").encode())
    assert printed_titles(folder) == []


def _set_title(twin: Path, written: str, front: str | None = None) -> None:
    """The twin's `\\title` line written as `written`, and `front.tex` beside main.tex holding
    `front`, where it is given."""
    main = twin / "manuscript" / "main.tex"
    main.write_bytes(main.read_text(encoding="utf-8").replace(_TWIN_TITLE, written).encode())
    if front is not None:
        (twin / "manuscript" / "front.tex").write_bytes(front.encode())


def test_a_title_in_iffalse_is_not_one_tex_prints(twin: Path) -> None:
    """Round 2 of #813: what `\\iffalse` leaves out prints nothing, so the `\\title` after it is
    the one title, and words of the other are not found in it."""
    _set_title(twin, "\\iffalse\n\\title{A title TeX never reads at all}\n\\fi\n" + _TWIN_TITLE)
    assert _title_answer(twin, "Reporting of hepatic injury with example-drug: a "
                               "disproportionality analysis") == []  # fmt: skip
    said = _title_answer(twin, "A title TeX never reads at all")
    assert [code for code, _message in said] == ["checklist-quote-not-found"]
    assert "is not under the \\title in main.tex" in said[0][1]


def test_a_title_set_only_in_an_input_file_is_read_there(twin: Path) -> None:
    """Round 2 of #813: a preamble that inputs its front matter sets the title in that file."""
    _set_title(twin, "\\input{front}", "\\title{The study of example-drug in an input file}\n")
    assert _title_answer(twin, "The study of example-drug in an input file") == []
    said = _title_answer(twin, "Reporting of hepatic injury with example-drug: a")
    assert [code for code, _message in said] == ["checklist-quote-not-found"]
    assert "is not under the \\title in front.tex" in said[0][1]


def test_two_titles_are_not_guessed_between(twin: Path) -> None:
    """Round 2 of #813: two `\\title`s TeX prints, in main.tex and in a file it inputs (and so
    a conditional's two branches), are not guessed between: the answer is told where each
    stands, and to keep one, and its quote is not held to either."""
    _set_title(twin, "\\input{front}\n" + _TWIN_TITLE,
               "\\title{An older title of the study}\n")  # fmt: skip
    said = _title_answer(twin, "Reporting of hepatic injury with example-drug: a")
    assert [code for code, _message in said] == ["checklist-location-unknown"]
    assert "front.tex line 1" in said[0][1] and "main.tex line 4" in said[0][1]


@pytest.mark.parametrize(("stage", "severity"),
                         [("drafting", "info"), ("internal-review", "warn"),
                          ("submission", "fail")])  # fmt: skip
def test_two_titles_are_told_as_a_quote_is_and_a_missing_quote_still_is_said(
    twin: Path, stage: str, severity: str
) -> None:
    """Round 3 of #813: the finding of two titles is told at the stage a quote's finding is,
    a note while drafting, a warning from internal review and a failure at submission; and an
    answer that quotes nothing is still said to, beside it."""
    _set_title(twin, "\\input{front}\n" + _TWIN_TITLE,
               "\\title{An older title of the study}\n")  # fmt: skip
    quoted = _title_said(twin, "Reporting of hepatic injury with example-drug: a", stage)
    assert [(code, said) for code, said, _message in quoted] == [
        ("checklist-location-unknown", severity)]
    unquoted = _title_said(twin, "", stage)
    assert [(code, said) for code, said, _message in unquoted] == [
        ("checklist-location-unknown", severity), ("checklist-quote-missing", severity)]


#: How a preamble defines `\title` rather than setting a title, each before the title set.
_TITLE_DEFINED = (
    "\\renewcommand\\title[1]{\\gdef\\thetitle{#1}}",
    "\\renewcommand*\\title[1]{\\gdef\\thetitle{#1}}",
    "\\providecommand\\title{A title defined and never set}",
    "\\newcommand\\title{A title defined and never set}",
    "\\def\\title{A title defined and never set}",
)


@pytest.mark.parametrize("defined", _TITLE_DEFINED)
def test_a_definition_of_title_is_no_title(tmp_path: Path, defined: str) -> None:
    """Round 3 of #813: `\\title` after a definer is the command being defined, which prints
    nothing there; the title is the one set after it."""
    from manuscript_guard.text.latex.printed import printed_titles

    folder = tmp_path / "manuscript"
    shutil.copytree(TWIN, folder)
    main = folder / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_bytes(text.replace(_TWIN_TITLE, f"{defined}\n{_TWIN_TITLE}").encode())
    assert [(t.path, t.line) for t in printed_titles(folder)] == [("main.tex", 4)]


def test_a_title_set_after_its_definition_is_held_to(twin: Path) -> None:
    """Round 3 of #813: so a quote of the title set is found, and one of the definition's
    words is not."""
    _set_title(twin, f"{_TITLE_DEFINED[3]}\n{_TWIN_TITLE}")
    assert _title_answer(twin, "Reporting of hepatic injury with example-drug: a") == []
    said = _title_answer(twin, "A title defined and never set")
    assert [code for code, _message in said] == ["checklist-quote-not-found"]


def test_a_title_s_notes_are_left_out_their_braces_nested(twin: Path) -> None:
    """Round 2 of #813: a `\\footnote` in the title prints as a note, as `\\thanks` does, and
    braces inside either do not end it early."""
    _set_title(twin, (
        "\\title{Hepatic injury with example-drug\\thanks{Funded by {the} grant {of {no} one}}"
        "\\footnote{See {the} note on {the} {data {held here}}} in synthetic reports}"))
    assert _title_answer(twin, "Hepatic injury with example-drug in synthetic reports") == []
    for note in ("Funded by the grant of no one", "See the note on the data held here"):
        said = _title_answer(twin, note)
        assert [code for code, _message in said] == ["checklist-quote-not-found"], note


def test_a_latex_manuscript_with_no_title_command_is_held_to_paper_yaml_s(twin: Path) -> None:
    """Where no file of the main text sets a `\\title`, the title is paper.yaml's."""
    main = twin / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_bytes(text.replace(_TWIN_TITLE + "\n", "").encode())
    assert _title_answer(twin, "Reporting of hepatic injury with example-drug: a "
                               "disproportionality analysis") == []  # fmt: skip
    said = _title_answer(twin, "Hepatic injury with example-drug in a cohort study")
    assert [code for code, _message in said] == ["checklist-quote-not-found"]
    assert "is not under the title in paper.yaml" in said[0][1]


def test_g7_reads_the_twins_quotations_and_cited_statements_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 8: the twin's cited statements, and the passages they are held to, are the
    example's, each at its `.tex` line."""
    from manuscript_guard.gates import check_passages, check_prose_quotations

    projekt = load_project(project)[0]
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    for check in (check_prose_quotations, check_passages):
        example, latex = check(projekt), check(twin)
        assert latex.counts == example.counts, check.__name__
        assert [(f.code, f.message) for f in latex.findings] == [
            (f.code, f.message) for f in example.findings
        ]
    assert check_passages(twin).counts["cited_statements"] == 3


def test_g8_recomputes_the_twins_statistics_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 8: each P and interval the twin prints, its values put in, is read as the
    example's is."""
    from manuscript_guard.gates.recomputed import check_recomputed

    projekt = load_project(project)[0]
    example = check_recomputed(projekt, *load_namespace(projekt)[:2])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_recomputed(twin, *load_namespace(twin)[:2])
    assert latex.counts == example.counts and example.counts["printed_intervals_read"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g12_reads_the_twins_methods_for_the_packages_used_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """The Methods the twin prints name statsmodels and not pandas or matplotlib, and cite
    none of them, as the example's do. The example's Deviations name the three, so the plan
    is read here without that entry."""
    from manuscript_guard.gates.software_methods import check_software_cited

    plan = project / "design" / "plan.md"
    text = plan.read_bytes().decode("utf-8")
    plan.write_bytes(text[: text.index("9. The Methods name statsmodels")].encode())
    projekt = load_project(project)[0]
    example = check_software_cited(projekt, load_namespace(projekt)[1])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_software_cited(twin, load_namespace(twin)[1])
    said = [(f.code, f.message, f.line, f.context) for f in example.findings]
    assert [(f.code, f.message, f.line, f.context) for f in latex.findings] == said
    assert [code for code, *_rest in said] == [
        "software-unnamed", "software-uncited", "software-unnamed"]  # fmt: skip
