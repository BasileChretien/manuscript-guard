"""Every gate and every command says what it does when it reads nothing.

A check that read nothing and passed is the failure this toolkit exists to prevent, and it
has happened here more than once: `audit --strict` of an empty paper printed "0 numeric
tokens" and exited 0; `bind` said "every number in the manuscript is accounted for" of a
folder that held no Markdown; a manuscript in `.qmd` failed `check` only through the
results it left unquoted. So each gate and each subcommand is in a table here, with what it
reads and what it does when that is nothing: a finding it reports, an exit code, or a
written reason why reading nothing is fine. One missing from the table fails the test, so a
new gate or command needs that decision before it is merged.

Where the table names a finding or an exit code, it is checked on a project with no
manuscript, no results and no figures: what `init` makes, less its `main.md`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pytest

from manuscript_guard import cli
from manuscript_guard.cli import build_parser, main


@dataclass(frozen=True)
class Zero:
    """What a gate or a command reads, and what it does when that is nothing."""

    reads: str
    #: For a gate, the key in `Report.counts` that says how much it read.
    count: str | None = None
    #: The finding reported when it read nothing, on a project with nothing in it.
    finding: str | None = None
    #: A command's exit code when it read nothing, and how it is run to show that.
    exits: int | None = None
    argv: tuple[str, ...] = ()
    #: Why reading nothing is fine, where it says nothing.
    why: str = ""


_NO_MANUSCRIPT = "the manuscript is empty, and G2 says so (`manuscript-empty`)"

GATES = {
    "G1": Zero("each results fragment, its script and its inputs", "fragments_checked",
               finding="no-results"),
    "G2": Zero("every number in the manuscript", "numeric_atoms", finding="manuscript-empty"),
    "G3": Zero("each figure, its script and its render", "figures_checked",
               why="a paper may have no figure"),
    "G4": Zero("the journal's profile and the main text", None, finding="no-journal-chosen"),
    "G6": Zero("the manuscript's prose", "prose_words", why=_NO_MANUSCRIPT),
    "G7": Zero("the citations, and the literature ledger", "citations",
               why="a paper may cite nothing and quote no number from the literature"),
    "G8": Zero("the quoted results that carry a number", "value_collisions",
               why="no results is G0's `no-results`"),
    "G8r": Zero("the reporting checklists the paper declares", "checklists",
                why="a paper may declare no reporting guideline; the reporting-checklist "
                "skill asks for one"),
    "G9": Zero("the analysis files, and the Methods paired with their steps", "analysis_files",
               why="with no analysis code there is nothing to read the Methods against"),
    "G10": Zero("the review of each figure", "figures_reviewed", why="no figure, no review"),
    "G11": Zero("the review panels and their readings", "review_rounds", finding="no-review"),
    "G12": Zero("the analysis plan, and the registrations paper.yaml lists", "design_sections",
                why="with no analysis code no plan is asked for; with code and no plan it "
                "is `no-analysis-plan`; a paper may list no registration, and a trial that "
                "lists none is `registration-missing`"),
    "G13": Zero("the rounds of revision", "revision_rounds",
                why="before a journal has answered there is nothing to respond to"),
    "G14": Zero("the manuscript's words", "abbreviations_read", why=_NO_MANUSCRIPT),
    "G15": Zero("the models the analysis fitted", "models",
                why="an analysis may fit no model"),
    "BUILD": Zero("each document as pandoc reads it", "documents_read_for_tex",
                  why=_NO_MANUSCRIPT),
}

#: `{project}` is the empty project; `{empty}` an empty Markdown file beside it.
COMMANDS = {
    "approve": Zero("the authors in authors.yaml", exits=2,
                    argv=("approve", "{project}", "--as", "Nobody Listed")),
    "audit": Zero("the papers and figures given, against the outputs given",
                  why="exits 1 under --strict when it read no number "
                  "(tests/test_cli.py, `test_audit_strict_fails_a_paper_with_no_number_in_it`); "
                  "it needs outputs to read against, which an empty project has not"),
    "bind": Zero("every unbound number in the manuscript", exits=2, argv=("bind", "{project}")),
    "build": Zero("the manuscript, once the gates pass",
                  why="the gates run first, and an empty manuscript fails them from the drafting "
                      "stage"),
    "check": Zero("every gate", exits=1, argv=("check", "{project}", "--stage", "drafting")),
    "checker": Zero("the items a co-author is asked to check", exits=2,
                    argv=("checker", "build", "{project}")),
    "checklist": Zero("the reporting guidelines the paper declares", exits=2,
                      argv=("checklist", "{project}")),
    "dictionary": Zero("the data dictionary", exits=2,
                       argv=("dictionary", "{project}", "--csv", "{project}/out.csv")),
    "explain": Zero("the numbers of the file it is given",
                    why="it explains one file and says when that file holds no number"),
    "fetch": Zero("a reporting guideline's published checklist",
                  why="it downloads what it is named, and refuses a name it does not know"),
    "hook": Zero("an agent tool's event", why="a hook never stops the tool that called it"),
    "impact": Zero("the records the gates read, for each file named or changed",
                   why="it says so when nothing has changed, and when nothing the gates "
                   "record depends on a file"),
    "import": Zero("a co-author's returned .docx",
                   why="a document it cannot read back is refused (exit 1)"),
    "init": Zero("nothing: it writes a project", why="it makes the files the others read"),
    "install-skills": Zero("the plugin's skills", why="it refuses when it finds none (exit 2)"),
    "journal": Zero("the journal profiles", why="it lists what there is, none included"),
    "lookup": Zero("the DOIs and PMIDs of the cited references", exits=2,
                   argv=("lookup", "{project}")),
    "methods": Zero("the analysis files", why="it prints `analysis_files`, 0 included"),
    "models": Zero("the models the analysis fitted", why="it says when there are none"),
    "palettes": Zero("the palettes shipped with the toolkit, nothing of a project",
                     why="it lists them all, and says so when a filter leaves none (exit 1)"),
    "passages": Zero("the sentences that cite, and the passages recorded for them",
                     why="it prints how many cited statements carry a passage, 0 of 0 "
                     "included"),
    "related": Zero("the earlier outputs in literature/related.yaml", exits=2,
                    argv=("related", "{project}")),
    "render": Zero("the manuscript", why="it says how many files it rendered, 0 included"),
    "values": Zero("the results, for a LaTeX manuscript's values file", exits=2,
                   argv=("values", "{project}")),
    "respond": Zero("the rounds of revision", exits=1, argv=("respond", "{project}")),
    "review": Zero("the review panels", why="it says there are none, and G11 says `no-review`"),
    "reworded": Zero("the manuscript now and as it was",
                     why="it prints how many files it compared, 0 included"),
    "sign": Zero("the findings a named person may sign off", exits=2,
                 argv=("sign", "{project}", "--as", "Nobody Listed", "--finding", "G15/x/y")),
    "search": Zero("the query it is given, then the registries' answers", exits=2,
                   argv=("search", "")),
    "stages": Zero("nothing: it prints the stages", why="it reads the policy table only"),
    "style": Zero("the citation style the journal's profile names", exits=2,
                  argv=("style", "{project}")),
    "proof": Zero("the proof given, against the document in the submission pack", exits=2,
                  argv=("proof", "{project}/paper.yaml", "{project}")),
    "submit": Zero("every gate at the submission stage, then the build", exits=1,
                   argv=("submit", "{project}")),
    "sync-bib": Zero("the citations in the manuscript", exits=2, argv=("sync-bib", "{project}")),
    "sync-sources": Zero("the citations in the manuscript", exits=2,
                         argv=("sync-sources", "{project}")),
    "transcribe": Zero("the reporting guidelines' sources",
                       why="a recipe whose source is missing is counted as failed (exit 1)"),
    "verify": Zero("the results fragments, re-run", exits=2, argv=("verify", "{project}")),
    "package": Zero("the results fragments, and the files that made them", exits=2,
                    argv=("package", "{project}")),
}


def _subcommands() -> set[str]:
    parser = build_parser()
    (found,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return set(found.choices)


def _gates_run(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[set[str], object]:
    """The names `check` runs its gates under, and its report."""
    names: set[str] = set()
    guarded = cli._guarded

    def recording(name, gate, unreadable=()):
        names.add(name)
        return guarded(name, gate, unreadable)

    monkeypatch.setattr(cli, "_guarded", recording)
    report, _project, _stage, _deferred = cli._run_gates(root, stage="drafting")
    return names, report


@pytest.fixture
def empty(tmp_path: Path) -> Path:
    """What `init` makes, with no manuscript and no plan: no results, no figures, no panel."""
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    for path in (*(root / "manuscript").rglob("*.md"), root / "design" / "plan.md"):
        path.unlink()
    return root


def test_every_command_is_in_the_table() -> None:
    assert set(COMMANDS) == _subcommands()


def test_every_gate_is_in_the_table(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names, report = _gates_run(project, monkeypatch)
    assert set(GATES) == names
    missing = {
        name: zero.count
        for name, zero in GATES.items()
        if zero.count is not None and zero.count not in report.counts
    }
    assert not missing, f"counts no gate reports on the example: {missing}"


def test_each_entry_says_what_happens_when_nothing_is_read() -> None:
    for name, zero in {**GATES, **COMMANDS}.items():
        said = [zero.finding, zero.exits, zero.why.strip() or None]
        assert sum(part is not None for part in said) == 1, name
        assert zero.reads, name
        assert zero.exits is None or zero.argv, name


def test_a_gate_that_reads_nothing_says_what_the_table_says(
    empty: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _names, report = _gates_run(empty, monkeypatch)
    codes = {finding.code for finding in report.findings}
    for name, zero in GATES.items():
        if zero.count is not None:
            assert not report.counts.get(zero.count), (name, "the empty project is not empty")
        if zero.finding is not None:
            assert zero.finding in codes, (name, zero.finding, sorted(codes))


@pytest.mark.parametrize("name", sorted(n for n, z in COMMANDS.items() if z.exits is not None))
def test_a_command_that_reads_nothing_exits_as_the_table_says(
    empty: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    zero = COMMANDS[name]
    argv = [part.format(project=empty) for part in zero.argv]
    assert main(argv) == zero.exits, capsys.readouterr()


# ---------------------------------------------------------------------------- LaTeX

#: What each command does with a LaTeX manuscript (DESIGN.md, "LaTeX manuscripts", step 1),
#: and how it is run to show it. A command that reads the manuscript only as Markdown read
#: nothing of one and said it found nothing, "rendered 0 files" or "cites nothing", or read the
#: `.tex` as Markdown: it refuses with a sentence and exits 2. One that reads it does so
#: through the reader, `check` with `not-read-in-latex` for each check not taught LaTeX yet.
#: `{tex}` is the project's `main.tex`. A command leaves "refuses" in the step that teaches it.
LATEX = {
    "approve": ("reads", ("approve", "{project}", "--as", "Nobody Listed")),
    "audit": ("refuses", ("audit", "{tex}", "--against", "{project}/results")),
    "bind": ("refuses", ("bind", "{project}")),
    "build": ("refuses", ("build", "{project}")),
    "check": ("reads", ("check", "{project}")),
    "checker": ("refuses", ("checker", "build", "{project}")),
    "checklist": ("no manuscript", ("checklist", "{project}")),
    "dictionary": ("no manuscript", ("dictionary", "{project}")),
    "explain": ("refuses", ("explain", "{tex}")),
    "fetch": ("no manuscript", ("fetch", "STROBE")),
    "hook": ("reads", ("hook", "session-start")),
    "impact": ("refuses", ("impact", "{project}/paper.yaml")),
    "import": ("refuses", ("import", "{project}/returned.docx", "{project}")),
    "init": ("refuses", ("init", "{project}")),
    "install-skills": ("no manuscript", ("install-skills",)),
    "journal": ("no manuscript", ("journal",)),
    # They find the citations through the reader's `citation_uses` (step 5).
    "lookup": ("reads", ("lookup", "{project}", "--dry-run")),
    "methods": ("refuses", ("methods", "{project}")),
    "models": ("refuses", ("models", "{project}")),
    # It packages the results, the scripts and the inputs whatever the format, and the `.tex`
    # sources with `--with-manuscript`; BOUND.md does not read LaTeX's bindings yet, and the
    # package says so with a warning (`package-bound-not-read`).
    "package": ("reads", ("package", "{project}")),
    "palettes": ("no manuscript", ("palettes",)),
    "passages": ("refuses", ("passages", "{project}")),
    "proof": ("refuses", ("proof", "{project}/proof.pdf", "{project}")),
    "related": ("refuses", ("related", "{project}")),
    "render": ("refuses", ("render", "{project}")),
    "respond": ("refuses", ("respond", "{project}")),
    "review": ("refuses", ("review", "{project}", "--run")),
    "reworded": ("refuses", ("reworded", "{project}")),
    "search": ("no manuscript", ("search", "hepatic injury")),
    "sign": ("refuses", ("sign", "{project}", "--as", "Nobody Listed", "--finding", "G15/x/y")),
    "stages": ("no manuscript", ("stages",)),
    "style": ("no manuscript", ("style", "{project}")),
    "submit": ("refuses", ("submit", "{project}")),
    "sync-bib": ("reads", ("sync-bib", "{project}")),
    "sync-sources": ("reads", ("sync-sources", "{project}")),
    "transcribe": ("no manuscript", ("transcribe",)),
    "values": ("reads", ("values", "{project}")),
    "verify": ("no manuscript", ("verify", "{project}")),
}


@pytest.fixture
def latex(empty: Path) -> Path:
    """The empty project with a LaTeX manuscript in it."""
    (empty / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nOf 4100 reports.\n\\end{document}\n",
        encoding="utf-8",
    )
    return empty


def _parsed(argv: tuple[str, ...], root: Path):
    tex = root / "manuscript" / "main.tex"
    return build_parser().parse_args([part.format(project=root, tex=tex) for part in argv])


def test_every_command_says_what_it_does_with_latex() -> None:
    assert set(LATEX) == _subcommands()
    # The table says what the code does: the refusing ones are those the guard holds.
    refusing = {name for name, (kind, _argv) in LATEX.items() if kind == "refuses"}
    assert refusing == set(cli._MARKDOWN_COMMANDS) | {"audit"}


@pytest.mark.parametrize("name", sorted(n for n, (kind, _) in LATEX.items() if kind == "refuses"))
def test_a_command_that_reads_only_markdown_refuses_a_latex_manuscript(
    latex: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _kind, argv = LATEX[name]
    tex = latex / "manuscript" / "main.tex"
    assert main([part.format(project=latex, tex=tex) for part in argv]) == 2
    said = capsys.readouterr().err
    assert "LaTeX" in said and said.count("\n") == 1, said
    assert not (latex / "manuscript" / "main.md").exists()


@pytest.mark.parametrize("name", sorted(n for n, (kind, _) in LATEX.items() if kind != "refuses"))
def test_a_command_that_reads_latex_or_no_manuscript_is_not_refused(latex: Path, name: str) -> None:
    _kind, argv = LATEX[name]
    assert cli._refused_for_latex(_parsed(argv, latex)) is None


def test_the_refusal_is_for_a_latex_manuscript_only(empty: Path) -> None:
    """A Markdown manuscript, a review that only shows where it stands, and lookup's journals
    are read as before."""
    (empty / "manuscript" / "main.md").write_text("# Results\n", encoding="utf-8")
    for argv in (("render", "{project}"), ("bind", "{project}"), ("init", "{project}")):
        assert cli._refused_for_latex(_parsed(argv, empty)) is None, argv
    # A header pandoc includes, named `main.tex` and declaring no class, beside it, and a
    # `.tex` named to `impact`, which follows the records of any file (round 1 of #404).
    (empty / "manuscript" / "main.tex").write_text("\\usepackage{booktabs}\n", "utf-8")
    for argv in (("render", "{project}"), ("impact", "{tex}")):
        assert cli._refused_for_latex(_parsed(argv, empty)) is None, argv
    (empty / "manuscript" / "main.md").unlink()
    (empty / "manuscript" / "main.tex").write_text("\\documentclass{article}\n", "utf-8")
    for argv in (
        ("review", "{project}"), ("lookup", "{project}", "--journals"),
        # A design round reads the plan, and a design override is no G15 finding (round 1 of
        # #404).
        ("review", "{project}", "--design", "--run"),
        ("sign", "{project}", "--as", "A", "--finding", "G12/design-override/1/x"),
        # Taking an earlier output's copy reads no manuscript.
        ("related", "{project}", "--take"),
        # `--files` is a flag here, no list of files (main's `review --files`).
        ("review", "{project}", "--files"),
    ):  # fmt: skip
        assert cli._refused_for_latex(_parsed(argv, empty)) is None, argv
