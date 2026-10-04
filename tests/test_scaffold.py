"""A fresh project must fail for the right reasons, and only those."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.findings import merge_all
from manuscript_guard.scaffold import init_project


def test_init_creates_the_layout(tmp_path: Path) -> None:
    created = init_project(tmp_path / "paper", title="A fresh project")
    names = {p.name for p in created}
    assert {"paper.yaml", "authors.yaml", "ledger.yaml", "attested.yaml", "main.md"} <= names
    for directory in ("analysis", "results", "literature/sources", "figures"):
        assert (tmp_path / "paper" / directory).is_dir()


def test_init_is_idempotent(tmp_path: Path) -> None:
    init_project(tmp_path / "paper")
    (tmp_path / "paper" / "paper.yaml").write_text("edited by hand\n", encoding="utf-8")
    assert init_project(tmp_path / "paper") == []
    assert (tmp_path / "paper" / "paper.yaml").read_text(encoding="utf-8") == "edited by hand\n"


def test_a_fresh_project_reads_as_a_todo_list(tmp_path: Path) -> None:
    """It should fail, but every failure must be real work rather than placeholder noise."""
    root = tmp_path / "paper"
    init_project(root, title="A fresh project")

    project, contract_report = load_project(root)
    _namespace, _results, _literature, load_report = load_namespace(project)
    report = merge_all([contract_report, load_report])

    assert not report.ok
    messages = [f.message for f in report.failures]
    assert any("no results fragments" in m for m in messages)
    assert sum("authors/0/given" in m or "authors/0/family" in m for m in messages) == 2
    # Optional fields the author has not filled in must not generate failures of their own.
    assert not any("orcid" in m or "email" in m or "credit" in m for m in messages)
    assert len(report.failures) == 3


def test_a_fresh_project_starts_at_design_and_passes_there(tmp_path: Path) -> None:
    """The scaffold wrote no `stage:`, so a new project fell to the `drafting` default.

    A project on its first day was held to the standards of one with a finished draft, which
    is precisely the wall of red the stage ladder was built to prevent — and reaching the
    documented experience needed a `--stage` flag the author had no reason to know about.
    """
    root = tmp_path / "paper"
    init_project(root, title="A fresh project")
    assert "stage: design" in (root / "paper.yaml").read_text(encoding="utf-8")

    from manuscript_guard.cli import _run_gates

    report, _project, chosen, deferred = _run_gates(root)
    assert chosen == "design"
    assert report.ok, report.render(root)
    assert deferred, "the outstanding work is still listed, just not yet due"


def test_a_scaffolded_project_passes_its_own_number_gate(tmp_path: Path) -> None:
    """The first thing a new user sees must not fail the rule it is explaining.

    The guidance paragraph named `p < 0.05` as an example of a convention and quoted two
    bindings to show the syntax. All three were read as manuscript text: the p-value is a
    convention only in Methods, and the two example keys do not exist. It is an HTML comment
    now, which also stops it reaching the built document if the author forgets to delete it.
    """
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    root.mkdir()
    init_project(root, title="T")
    report, _project, _stage, _deferred = _run_gates(root, stage="drafting")
    numbers = [f for f in report.findings if f.gate == "G2"]
    assert not numbers, "\n".join(f.message for f in numbers)


def test_init_ships_the_gitattributes_the_digests_depend_on(tmp_path: Path) -> None:
    """A scaffolded project must not inherit the bug this repository already cured.

    manuscript-guard's guarantees are byte-level — the .sha256 beside each fragment, the
    manuscript digest a review record is tied to. Git's default stores LF and hands Windows
    CRLF, so the same commit hashes differently on two machines and `check` reports an edit
    nobody made. This repository's own .gitattributes records that CI failed exactly that way;
    `init` shipped a .gitignore and no .gitattributes, so the fix protected the toolkit and
    not its users.
    """
    init_project(tmp_path / "paper")
    written = (tmp_path / "paper" / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in written
    # Figures and the built .docx are digested as bytes; normalising them would corrupt them.
    # Matched on the fields, not the spacing, which is column-aligned for reading.
    marked = {line.split()[0] for line in written.splitlines() if line.endswith("binary")}
    assert {"*.docx", "*.png", "*.pdf", "*.xlsx"} <= marked


def test_init_writes_the_rules_any_agent_tool_reads(tmp_path: Path) -> None:
    """Several agent tools read an `AGENTS.md` at a project's root on their own, whether or
    not the skills are installed. So the rules the guarantee rests on are in every new
    project: machine-written files are not edited, `check` runs before a build, and nobody
    but `check` decides that the manuscript is clean."""
    root = tmp_path / "paper"
    created = init_project(root, title="A fresh project")
    rules = root / "AGENTS.md"
    assert rules in created
    text = " ".join(rules.read_text(encoding="utf-8").split())

    assert "Never edit a machine-written file" in text
    for generated in ("`results/`", "`build/`", "`profiles/reporting/<NAME>.yaml`"):
        assert generated in text, generated
    # The one file under profiles/reporting/ an author does edit, which the rule must not
    # seem to forbid. For a guideline that ships, there is none there until the author makes
    # one, and the rule says what one is for.
    assert "a recipe in `profiles/reporting/recipes/`, which is used in place of the one" in text
    assert "Run `manuscript-guard check` before `manuscript-guard build`" in text
    assert "`manuscript-guard check --submission`" in text
    assert "Never decide for yourself that the manuscript is clean" in text
    # The templates go through str.format, so a binding is written with four braces there
    # and has to come out with two.
    assert "`{{results.<key>}}`" in text and "{{{" not in text
    assert b"\r" not in rules.read_bytes()


def test_the_rules_forbid_no_number_that_check_accepts(project: Path, capsys) -> None:
    """The rule on numbers said one is "never a typed literal". `check` accepts a typed number
    that is a convention of writing or a pointer, and the worked example, which carries the
    rules, is full of them. Taken at its word the rule could not be followed ("Table 2" has
    no binding), and with the rule against changing a convention to make a check pass it told
    an agent never to declare one."""
    from manuscript_guard.cli import main
    from manuscript_guard.scaffold import AGENTS

    capsys.readouterr()
    assert main(["explain", str(project / "manuscript" / "main.md")]) == 0
    explained = capsys.readouterr().out
    assert "convention" in explained and "structural" in explained
    assert main(["check", str(project)]) == 0
    capsys.readouterr()

    rule = " ".join(AGENTS.split())
    assert "never a typed literal" not in rule

    # Each kind of typed number in this sentence that `check` accepts has its word in the
    # rule. The classifier has more rules than these six; they are the ones a convention, a
    # pointer, a label and a name stand for. The finding is the one it refuses.
    typed = project / "manuscript" / "typed.md"
    typed.write_text(
        "# Methods\n\nEvents of grade 3 in patients aged 18-64 years were coded with ICD-10 "
        "(R version 4.3.1). See Table 1 for the 95% confidence intervals. The mean was 3.84.\n",
        encoding="utf-8",
    )
    main(["explain", str(typed)])
    rows = [line.split() for line in capsys.readouterr().out.splitlines() if line.split()]
    verdicts = {row[2]: (row[0], row[4]) for row in rows}
    assert verdicts["3.84"][0] == "FAIL", verdicts
    said_as = {
        "confidence-level": "a convention of writing",
        "cross-reference": "a pointer",
        "categorical-label": "a label",
        "age-band": "a label",
        "software-version": "a name",
        "terms": "a name",
    }
    accepted = {how for verdict, how in verdicts.values() if verdict == "ok"}
    assert accepted == set(said_as), accepted
    for how in sorted(accepted):
        assert said_as[how] in rule, f"{how}: the rule does not say {said_as[how]!r}"


def test_the_rules_promise_nothing_the_readme_may_not_hold() -> None:
    """The file is written once and read for as long as the project lives, under whatever
    agent tool. It said the README "says how to install" the skills, when the README held
    the commands of one agent tool only."""
    from manuscript_guard.scaffold import AGENTS

    closing = " ".join(AGENTS.split())
    assert "says how to install them" not in closing
    assert "says which agent tools they can be installed in, and how" in closing


def test_rules_that_are_already_there_are_left_and_the_ones_to_add_are_printed(
    tmp_path: Path, capsys
) -> None:
    """`init` never overwrites. A repository that already has an `AGENTS.md` keeps it, and
    without a word an agent working there would have no rule about `results/` at all."""
    from manuscript_guard.cli import main

    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("# House rules\n", encoding="utf-8")
    assert main(["init", str(root), "--title", "T"]) == 0
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "# House rules\n"
    said = capsys.readouterr().out
    assert "AGENTS.md was already there" in said
    # Every line of the file but its heading, which the repository's own file has already.
    from manuscript_guard.scaffold import AGENTS

    heading, rules = AGENTS.format(title="T").split("\n", 1)
    assert heading.startswith("# ") and rules.strip() in said
    assert heading not in said


def test_init_does_not_print_rules_that_are_in_the_file(tmp_path: Path, capsys) -> None:
    from manuscript_guard.cli import main

    root = tmp_path / "paper"
    assert main(["init", str(root), "--title", "T"]) == 0
    first = capsys.readouterr().out
    assert "AGENTS.md" in first and "Never edit a machine-written file" not in first
    # Run again on the project it made: the file is there, and it holds the rules.
    assert main(["init", str(root), "--title", "T"]) == 0
    assert "Never edit a machine-written file" not in capsys.readouterr().out


def test_the_advice_names_an_emitter_that_exists(
    project: Path, tmp_path: Path, capsys
) -> None:
    """`init`, the no-results hint and the no-digest hint all said to call emit(). There is
    no emit(): it is Emitter(...).write() in Python and mg_emitter() in R."""
    import re

    from manuscript_guard.cli import main
    from manuscript_guard.emit import Emitter
    from manuscript_guard.gates import check_freshness

    root = tmp_path / "fresh"
    assert main(["init", str(root), "--title", "T"]) == 0
    said = [capsys.readouterr().out]

    fresh, _ = load_project(root)
    _namespace, _results, _lit, load_report = load_namespace(fresh)
    said += [f.hint for f in load_report.findings if f.code == "no-results"]

    (project / "results" / "01_disproportionality.json.sha256").unlink()
    example, _ = load_project(project)
    _namespace, results, _lit, _r = load_namespace(example)
    said += [f.hint for f in check_freshness(example, results).findings if f.code == "no-digest"]

    assert len(said) == 3, said
    r_source = (Path(__file__).parent.parent / "r" / "manuscriptguard" / "R" / "emit.R").read_text(
        encoding="utf-8"
    )
    for text in said:
        assert "emit()" not in text, text
        assert "Emitter(" in text and "mg_emitter(" in text, text
    assert callable(Emitter.write)
    assert re.search(r"^mg_emitter <- function", r_source, re.MULTILINE)


def test_init_writes_a_title_that_is_read_as_it_was_typed(tmp_path: Path) -> None:
    """`init --title` typed the title between double quotation marks itself. A backslash in
    it began an escape, which `check` now refuses and the author did not type, and a
    quotation mark ended the title, after which the project could not be read at all."""
    title = "Effect of $" + chr(92) + 'nu$ on "survival"'
    root = tmp_path / "paper"
    init_project(root, title=title)

    project, report = load_project(root)
    assert project.paper["title"] == title
    assert not [f for f in report.failures if f.message.startswith("title")]


#: Titles `init --title` may be given. Each left a new project that failed `check`, on the
#: header `init` itself typed into `manuscript/main.md` or, for the tab, on `paper.yaml`;
#: all but the line break, where `check` passed with two titles that no command spoke of,
#: the header's being the first line only.
AWKWARD_TITLES = {
    "a quotation mark": 'A "quoted" title',
    "TeX that YAML does not read": "Effect of $" + chr(92) + "delta$ on outcomes",
    "a closing backslash": "Outcomes of Foo" + chr(92),
    "TeX and a closing quotation mark": "Effect of $" + chr(92) + 'nu$ on "survival"',
    "an apostrophe, a quotation mark and TeX": "Crohn's " + '"disease" and $' + chr(92) + "mu$",
    "a tab": "Alpha" + chr(9) + "beta",
    "a line break": "First part" + chr(10) + "second part",
}


@pytest.mark.parametrize("case", list(AWKWARD_TITLES))
def test_init_with_an_awkward_title_gives_a_project_that_passes_check(
    case: str, tmp_path: Path, capsys
) -> None:
    """From the command to `check` on what it made. A tab and a line break in a title are
    written as a space, which is what the build prints for each."""
    from manuscript_guard.cli import _run_gates, main

    title = AWKWARD_TITLES[case]
    root = tmp_path / "paper"
    assert main(["init", str(root), "--title", title]) == 0
    assert main(["check", str(root)]) == 0, capsys.readouterr().out

    report, project, _chosen, _deferred = _run_gates(root)
    assert project.paper["title"] == " ".join(title.replace(chr(9), " ").split(chr(10)))
    assert not {f.code for f in report.findings} & {"schema-violation", "front-matter-unreadable"}
    # The header's title is what the build compares with paper.yaml's, and warns of.
    from manuscript_guard.build.assemble import strip_front_matter

    header = strip_front_matter((root / "manuscript" / "main.md").read_text(encoding="utf-8"))[1]
    assert header in ("", project.paper["title"])
    readme = (root / "README.md").read_text(encoding="utf-8").splitlines()
    assert readme[0] == "# " + project.paper["title"], "the heading was broken over two lines"


#: How the manuscript's own header holds each: between double quotation marks as it always
#: did where YAML reads that back as the title, between single ones where a backslash or a
#: double quotation mark would not, and not at all where neither does.
HEADER = {
    "Untitled manuscript": 'title: "Untitled manuscript"',
    # Three hyphens, a dash as TeX writes it, are also what closes the header.
    "Outcomes---a cohort": 'title: "Outcomes---a cohort"',
    "Crohn's disease: a cohort": "title: " + '"' + "Crohn's disease: a cohort" + '"',
    'A "quoted" title': "title: 'A " + '"quoted"' + " title'",
    "Effect of $" + chr(92) + "delta$ on outcomes": (
        "title: 'Effect of $" + chr(92) + "delta$ on outcomes'"
    ),
    # Neither kind of mark gives these back: both kinds in the title, or a backslash, which
    # double marks read as an escape, and an apostrophe, which ends single ones.
    "Crohn's " + '"disease"': None,
    "TNF-$" + chr(92) + "alpha$ inhibitors in Crohn's disease": None,
    # A mark of the title's own at either end. While the build read the header by line and
    # stripped every quotation mark at either end, none of these could be read back, and
    # the header was left out: typed, it read `the patients`, two titles. Read as YAML,
    # each is held by the other kind of mark.
    'Outcomes of "Foo"': "title: '" + 'Outcomes of "Foo"' + "'",
    '"Quoted" at the start': "title: '" + '"Quoted" at the start' + "'",
    "the patients'": "title: " + '"' + "the patients'" + '"',
    "'Tis the season": "title: " + '"' + "'Tis the season" + '"',
    # White space the comparison folds: the header holds the title as it was given.
    "A  cohort study": 'title: "A  cohort study"',
}


@pytest.mark.parametrize("title", list(HEADER))
def test_the_manuscripts_header_holds_the_title_where_it_reads_back_as_typed(
    title: str, tmp_path: Path
) -> None:
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text.masking import folded

    root = tmp_path / "paper"
    init_project(root, title=title)
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")

    if HEADER[title] is None:
        assert text.startswith("# Introduction"), "no header, so paper.yaml's is the only title"
        init_project(tmp_path / "usual")
        usual = (tmp_path / "usual" / "manuscript" / "main.md").read_text(encoding="utf-8")
        assert text == usual.split(chr(10), 4)[4], "and what follows the header is unchanged"
        return
    header = "---" + chr(10) + HEADER[title] + chr(10) + "---" + chr(10) * 2
    assert text.startswith(header + "# Introduction")
    # The build's reading of it, which is YAML's with the white space folded.
    assert strip_front_matter(text)[1] == folded(title)
    assert yaml.safe_load(HEADER[title]) == {"title": title}


def test_an_ordinary_title_is_typed_into_paper_yaml_as_it_always_was(tmp_path: Path) -> None:
    root = tmp_path / "paper"
    init_project(root, title="Crohn's disease: a cohort")
    lines = (root / "paper.yaml").read_text(encoding="utf-8").splitlines()
    assert lines[1] == 'title: "Crohn' + "'" + 's disease: a cohort"'


#: Characters no document can carry. The first is what Python makes of an argument that is
#: not in the terminal's encoding: a lone surrogate, which no file can carry either, since
#: it cannot be written as UTF-8.
NOT_A_TITLE = {
    "a lone surrogate": chr(0xDCE9),
    "another": chr(0xD800),
    "a control character": chr(7),
    "a non-character": chr(0xFFFF),
}


@pytest.mark.parametrize("case", list(NOT_A_TITLE))
def test_init_refuses_a_title_no_file_can_hold_before_it_makes_anything(
    case: str, tmp_path: Path, capsys
) -> None:
    """On a surrogate `init` ended in a traceback with the folders made and `paper.yaml`
    empty, and a second `init` with a good title kept that empty file, since it writes over
    nothing: the project could not be read. On the others it made a project `check` failed
    or could not read."""
    from manuscript_guard.cli import main

    root = tmp_path / "paper"
    assert main(["init", str(root), "--title", "Caf" + NOT_A_TITLE[case] + " study"]) == 2
    said = capsys.readouterr().err
    assert "Traceback" not in said
    assert "the title" in said
    assert "which no document can carry" in said
    assert "no file" not in said, "a control character is one a file can carry"
    assert not root.exists(), "nothing was made"


#: Titles with TeX the document would be printed without, and what `init` says of each.
TEX_IN_A_TITLE = {
    "outside dollar signs": (
        "IFN-" + chr(92) + "gamma release assays",
        "`" + chr(92) + "gamma` stands outside dollar signs",
    ),
    "before a number": (
        "Outcomes at 12 " + chr(92) + "pm 3 months",
        "`" + chr(92) + "pm` stands outside dollar signs",
    ),
    "past a bracket": (
        "[18F]FDG and TGF-$" + chr(92) + "beta$",
        "`" + chr(92) + "beta` stands after a `[`",
    ),
}


@pytest.mark.parametrize("case", list(TEX_IN_A_TITLE))
def test_init_refuses_a_title_whose_tex_check_would_fail(
    case: str, tmp_path: Path, capsys
) -> None:
    """`init --title "IFN-\\gamma release assays"` made a project whose title `check`
    passed and the build printed `IFN-release assays`. `check` fails that title now. It
    reports it once, at `paper.yaml`, but `init` types the title into the manuscript's
    header too, so a project made with it would open on a finding with the title to mend
    in two files. The title is refused before anything is made, in the finding's words and
    with its hint. The refusal does not say the title cannot be printed whole: past a sign
    pandoc may well print it whole, and the finding says "may"."""
    from manuscript_guard.cli import main

    title, says = TEX_IN_A_TITLE[case]
    root = tmp_path / "paper"
    assert main(["init", str(root), "--title", title]) == 2
    said = capsys.readouterr().err
    assert "Traceback" not in said
    assert says in said
    assert "nothing was made" in said
    assert "cannot be printed whole" not in said
    assert "for italics write `*in vivo*`" in said, "the hint, which has the other remedies"
    assert not root.exists()


def test_init_takes_a_title_with_its_tex_between_dollar_signs(tmp_path: Path, capsys) -> None:
    from manuscript_guard.cli import main

    title = "IFN-$" + chr(92) + "gamma$ release assays"
    root = tmp_path / "paper"
    assert main(["init", str(root), "--title", title]) == 0
    assert main(["check", str(root)]) == 0, capsys.readouterr().out
    project, _report = load_project(root)
    assert project.paper["title"] == title
