"""A fresh project must fail for the right reasons, and only those."""

from __future__ import annotations

from pathlib import Path

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
    # seem to forbid.
    assert "`profiles/reporting/recipes/`" in text
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
    assert "a convention of writing" in rule and "a pointer" in rule


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
