"""What `next` reads and what it says: the state, the actions, and the words of a command."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.findings import FAIL, Finding
from manuscript_guard.guide.routes import GATE_RANK
from manuscript_guard.policy import DRAFTING, STAGES
from manuscript_guard.scaffold import ENGLISHES

SCHEMA = "manuscript-guard/next/1"
NO_PROJECT, AUTHORS_ONLY, UNREADABLE, PROJECT = "none", "authors-only", "unreadable", "project"
AGENT, AUTHOR, ASK = "agent", "author", "ask-author"
#: The gates `counts.by_gate` always holds, failing or not; another gate a finding names is
#: added beside them.
COUNTED_GATES = (*(f"G{n}" for n in range(17)), "BUILD")
#: The gates whose failures are a number's source (tier 5).
PROVENANCE = frozenset({"G2", "G3", "G7", "G8"})
#: The codes a choice of tier 4 answers: a finding of one is in that choice, not listed again.
CHOICE_CODES = frozenset({
    "no-journal-chosen", "journal-profile-missing", "english-variant-mismatch",
    "english-variant-undeclared", "reporting-guideline-for-design",
})  # fmt: skip
#: Papers `next` offers to bring in where there is no project: in the folder itself, not
#: below it, and not a repository's own notes.
PAPER_SUFFIXES = (".docx", ".md", ".tex")
NOT_PAPERS = frozenset({"readme", "changelog", "contributing", "licence", "license", "agents",
                        "claude"})  # fmt: skip
SHOWN_FINDINGS = 5
LATEX_CHECKER = ("the co-author checker does not read a LaTeX manuscript yet, so where its "
                 "round stands is not shown and no page is offered")  # fmt: skip


@dataclass(frozen=True)
class Checker:
    """Where the co-authors' checks stand: `checker status` in four numbers."""

    items: int
    outstanding: int
    stale: int
    disagreements: int


@dataclass(frozen=True)
class State:
    """What `decide` reads: everything `inspect` found, and nothing it has to read again."""

    kind: str = PROJECT
    root: Path = Path(".")
    #: Where `next` was run: a command names the project's folder unless it is this one.
    cwd: Path | None = None
    format: str | None = "markdown"
    error: str | None = None
    #: Where there is no project: the papers in the folder, by name.
    candidates: tuple[str, ...] = ()
    stage: str | None = DRAFTING
    findings: tuple[Finding, ...] = ()
    deferred: Mapping[str, int] = field(default_factory=dict)
    #: Each `FILE:LINE` whose unbound numbers each read as one published value, with the
    #: bindings `bind --apply --only FILE:LINE` would write there.
    bindable: Mapping[str, str] = field(default_factory=dict)
    checker: Checker | None = None
    notes: tuple[str, ...] = ()
    target_journal: str | None = None
    english_variant: str | None = None
    reporting_guidelines: tuple[str, ...] = ()
    study_type: str | None = None
    #: The journals `set target_journal` takes here.
    journals: tuple[str, ...] = ()
    #: The English the target journal's profile asks for, where it names one.
    journal_english: str | None = None
    #: Each study design: its key, its label and its reporting guidelines.
    study_types: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    englishes: tuple[str, ...] = ENGLISHES


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    effect: str
    argv: tuple[str, ...]
    who: str = AGENT
    placeholders: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Choice:
    question: str
    options: tuple[Option, ...]
    recommended: str | None = None


@dataclass(frozen=True)
class Action:
    id: str
    rule: str
    tier: int
    title: str
    why: str
    who: str = AGENT
    skill: str | None = None
    argv: tuple[str, ...] | None = None
    codes: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    choice: Choice | None = None
    #: Where it goes within its tier; not part of what is printed.
    key: tuple = field(default=(0, "", "", 0), compare=False, repr=False)

    @property
    def count(self) -> int:
        return len(self.findings)


#: Commands that take the project as `--path`, those that take none, and those whose path
#: comes after a first positional.
_PATH_OPTION = frozenset({"set", "checklist"})
_NO_PATH = frozenset({"stages", "palettes", "search", "fetch", "transcribe", "install-skills",
                      "explain", "audit"})  # fmt: skip
_PATH_SECOND = frozenset({"checker", "proof", "import"})
_PLAIN_WORD = re.compile(r"[A-Za-z0-9_./:@%+=,-]+|<[A-Z_]+>")


def argv(state: State, *words: str) -> tuple[str, ...]:
    """A command's words, naming the project's folder where `next` was run elsewhere."""
    command, rest = words[0], list(words[1:])
    if command in _NO_PATH or (state.cwd is not None and state.cwd == state.root):
        return (command, *rest)
    where = state.root.as_posix()
    if command in _PATH_OPTION:
        return (command, *rest, "--path", where)
    if command in _PATH_SECOND:
        return (command, rest[0], where, *rest[1:])
    return (command, where, *rest)


def shown(words: tuple[str, ...] | None) -> str | None:
    """The command as it is written at a prompt, a placeholder left as it stands."""
    if words is None:
        return None
    quoted = (w if _PLAIN_WORD.fullmatch(w) else shlex.quote(w) for w in words)
    return " ".join(("manuscript-guard", *quoted))


def _file(state: State, name: str) -> str:
    """A file of the folder `next` read, as a command run where `next` was run names it."""
    if state.cwd is not None and state.cwd == state.root:
        return name
    return (state.root / name).as_posix()


def _rank(gate: str) -> int:
    return GATE_RANK.index(gate) if gate in GATE_RANK else len(GATE_RANK)


def _where(finding: Finding, root: Path) -> str:
    if finding.path is None:
        return ""
    try:
        return Path(finding.path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(finding.path).as_posix()


def _in_order(findings, root: Path) -> tuple[Finding, ...]:
    return tuple(sorted(findings, key=lambda f: (
        _rank(f.gate), f.code, _where(f, root), f.line or 0, f.message, f.severity)))  # fmt: skip


def _stage_at_least(state: State, stage: str) -> bool:
    return state.stage in STAGES and STAGES.index(state.stage) >= STAGES.index(stage)


def _failing(state: State) -> list[Finding]:
    return [f for f in state.findings if f.severity == FAIL]


def _codes(state: State) -> set[str]:
    return {f.code for f in state.findings}


WHY = {
    "cannot-check": "Rule cannot-check (tier 0): a gate that could not read its file has "
    "checked nothing, so every other answer waits on this one.",
    "start": "Rule start (tier 1): there is no project here, and nothing can be checked until "
    "there is one.",
    "stale-results": "Rule stale-results (tier 2): the results are not those the analysis "
    "makes now, so every number bound to them waits on this.",
    "plan": "Rule plan (tier 3): the analysis plan comes before the numbers that answer it.",
    "choose-journal": "Rule choose-journal (tier 4): the journal's limits and statements are "
    "checked only once it is named and its profile written.",
    "choose-english": "Rule choose-english (tier 4): G14 holds the spelling to the English "
    "declared, and to the one most words are in where none is.",
    "choose-guideline": "Rule choose-guideline (tier 4): no checklist is asked for until the "
    "paper declares the guideline it follows.",
    "choose-study-type": "Rule choose-study-type (tier 4): the design decides which plan "
    "sections G12 asks for and which guideline is offered.",
    "provenance": "Rule provenance (tier 5): a number with no source is the failure the "
    "toolkit exists to prevent.",
    "failures": "Rule failures (tier 6): it fails now, in gate order once what it rests on "
    "is put right.",
    "co-author-checks": "Rule co-author-checks (tier 7): a round of co-authors' checks is "
    "open, and an answer about changed text counts for nothing.",
    "warnings": "Rule warnings (tier 8): nothing fails, but these are worth reading now.",
    "advance": "Rule advance (tier 9): nothing fails at this stage.",
    "optional": "Rule optional (tier 10): a step an author may take once nothing fails at "
    "internal review or later; none is required by a gate.",
}
