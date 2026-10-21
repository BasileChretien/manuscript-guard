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
    "render": Zero("the manuscript", why="it says how many files it rendered, 0 included"),
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
    "submit": Zero("every gate at the submission stage, then the build", exits=1,
                   argv=("submit", "{project}")),
    "sync-bib": Zero("the citations in the manuscript", exits=2, argv=("sync-bib", "{project}")),
    "sync-sources": Zero("the citations in the manuscript", exits=2,
                         argv=("sync-sources", "{project}")),
    "transcribe": Zero("the reporting guidelines' sources",
                       why="a recipe whose source is missing is counted as failed (exit 1)"),
    "verify": Zero("the results fragments, re-run", exits=2, argv=("verify", "{project}")),
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
