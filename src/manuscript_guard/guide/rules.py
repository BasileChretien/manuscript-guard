"""`decide`: the rules, in the order their tiers are tried, each a pure function of the
state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import WARN, Finding
from manuscript_guard.guide.model import (
    AGENT,
    ASK,
    AUTHOR,
    AUTHORS_ONLY,
    CHOICE_CODES,
    NO_PROJECT,
    PROJECT,
    PROVENANCE,
    UNREADABLE,
    WHY,
    Action,
    Choice,
    Option,
    State,
    _codes,
    _failing,
    _file,
    _in_order,
    _rank,
    _stage_at_least,
    _where,
    argv,
)
from manuscript_guard.guide.routes import CANNOT_CHECK, GATE_SKILLS, Route, route_of
from manuscript_guard.policy import DESCRIPTIONS, DRAFTING, INTERNAL_REVIEW, STAGES, SUBMISSION


def _tier_of(finding: Finding) -> int:
    if finding.code in CANNOT_CHECK:
        return 0
    if finding.gate == "G1":
        return 2
    if finding.gate == "G12":
        return 3
    return 5 if finding.gate in PROVENANCE else 6


def _grouped(state: State, rule: str, tier: int, findings, verb: str) -> list[Action]:
    """One action per code: its route's skill and command, or its gate's where it has none."""
    by_code: dict[str, list[Finding]] = {}
    for finding in findings:
        by_code.setdefault(finding.code, []).append(finding)
    actions = []
    for code, group in by_code.items():
        ordered = _in_order(group, state.root)
        first = ordered[0]
        route = route_of(code)
        why = WHY[rule]
        if route is None:
            route = Route(GATE_SKILLS.get(first.gate), ("check",))
            why += f" No route names {code}, so it is sent to {first.gate}'s skill, with `check`."
        actions.append(Action(
            id=f"{rule}:{code}", rule=rule, tier=tier,
            title=f"{verb}: {code}, {len(group)} in {first.gate}", why=why, who=route.who,
            skill=route.skill, argv=argv(state, *route.argv) if route.argv else None,
            codes=(code,), findings=ordered,
            key=(_rank(first.gate), code, _where(first, state.root), first.line or 0),
        ))  # fmt: skip
    return actions


def _cannot_check(state: State) -> list[Action]:
    if state.kind == UNREADABLE:
        return [Action(
            id="cannot-check:paper.yaml", rule="cannot-check", tier=0, who=AUTHOR,
            title="paper.yaml cannot be read, so nothing has been checked",
            why=f"{WHY['cannot-check']} {state.error}", skill="project-setup",
            argv=argv(state, "check"),
        )]  # fmt: skip
    failing = [f for f in _failing(state) if _tier_of(f) == 0]
    return _grouped(state, "cannot-check", 0, failing, "Put right what stops a gate")


def _tiered(rule: str, tier: int, verb: str) -> Callable[[State], list[Action]]:
    def build(state: State) -> list[Action]:
        failing = [f for f in _failing(state)
                   if _tier_of(f) == tier and f.code not in CHOICE_CODES]  # fmt: skip
        if rule == "provenance":
            return _provenance(state, failing)
        return _grouped(state, rule, tier, failing, verb)

    return build


def _provenance(state: State, failing: list[Finding]) -> list[Action]:
    """A number one published value reads as is bound by its own command, asked of the
    author; the rest of the tier is grouped by code."""
    rest: list[Finding] = []
    at: dict[str, list[Finding]] = {}
    for finding in failing:
        where = f"{_where(finding, state.root)}:{finding.line}"
        if finding.code == "unclassified-number" and where in state.bindable:
            at.setdefault(where, []).append(finding)  # several numbers on a line: one action
        else:
            rest.append(finding)
    actions = []
    for where, group in at.items():
        ordered = _in_order(group, state.root)
        first = ordered[0]
        actions.append(Action(
            id=f"provenance:bind:{where}", rule="provenance", tier=5, who=ASK,
            title=f"Bind the number at {where} to {state.bindable[where]}",
            why=WHY["provenance"] + " Each number there reads as exactly one published value, "
            "and its binding prints the same characters.",
            skill="results-binding", argv=argv(state, "bind", "--apply", "--only", where),
            codes=(first.code,), findings=ordered,
            key=(_rank(first.gate), first.code, _where(first, state.root), first.line or 0),
        ))  # fmt: skip
    return actions + _grouped(state, "provenance", 5, rest, "Give the numbers a source")


def _choice_action(rule: str, title: str, skill: str | None, choice: Choice, findings,
                   state: State, index: int) -> Action:  # fmt: skip
    found = _in_order(findings, state.root)
    return Action(
        id=f"{rule}", rule=rule, tier=4, title=title, why=WHY[rule], who=AUTHOR, skill=skill,
        codes=tuple(sorted({f.code for f in found})), findings=found, choice=choice,
        key=(index, "", "", 0),
    )  # fmt: skip


def _choose_journal(state: State) -> list[Action]:
    codes = _codes(state)
    missing = "journal-profile-missing" in codes
    if not missing and not (state.target_journal is None and _stage_at_least(state, DRAFTING)):
        return []
    target = state.target_journal
    options = []
    if missing and target:
        options.append(Option(
            "profile", f"Write the profile of {target}",
            f"copies the annotated template to profiles/journals/{target}.yaml, for the "
            "journal-profile skill to fill from the journal's own page",
            argv(state, "journal", "--template", target),
        ))  # fmt: skip
    for journal in state.journals:
        if journal == target:
            continue
        options.append(Option(
            f"set:{journal}", f"Write for {journal}",
            f"paper.yaml names {journal}, and G4 holds the paper to its profile",
            argv(state, "set", "target_journal", journal), who=ASK if target else AGENT,
        ))  # fmt: skip
    if not target:
        options.append(Option(
            "new", "Another journal: start its profile",
            "copies the annotated template to profiles/journals/<SLUG>.yaml; once the "
            "journal-profile skill has filled it, `set target_journal <SLUG>` names it",
            argv(state, "journal", "--template", "<SLUG>"),
            placeholders={"SLUG": "a short name for the journal, as its profile is named"},
        ))  # fmt: skip
    recommended = "profile" if missing and target else (
        f"set:{state.journals[0]}" if len(state.journals) == 1 and not target else None)
    question = (f"There is no profile of {target}: write it, or choose another journal?"
                if missing and target else "Which journal is the paper for?")  # fmt: skip
    found = [f for f in state.findings
             if f.code in ("journal-profile-missing", "no-journal-chosen")]  # fmt: skip
    return [_choice_action("choose-journal", "Choose the journal", "journal-profile",
                           Choice(question, tuple(options), recommended), found, state, 0)]


ENGLISH_NAMES = {"en-GB": "British English", "en-US": "American English"}


def _choose_english(state: State) -> list[Action]:
    found = [f for f in state.findings if f.code.startswith("english-variant-")]
    if not found and not (state.english_variant is None and _stage_at_least(state, DRAFTING)):
        return []
    options = tuple(
        Option(english, ENGLISH_NAMES.get(english, english),
               f"paper.yaml declares {english}, and G14 holds the spelling to it",
               argv(state, "set", "english_variant", english))
        for english in state.englishes if english != state.english_variant
    )  # fmt: skip
    wanted = state.journal_english if state.journal_english in state.englishes else None
    question = (f"The journal asks for {ENGLISH_NAMES.get(wanted, wanted)}: declare it?"
                if wanted else "Which English is the paper written in?")  # fmt: skip
    return [_choice_action("choose-english", "Declare the paper's English", "journal-profile",
                           Choice(question, options, wanted), found, state, 1)]


def _choose_guideline(state: State) -> list[Action]:
    found = [f for f in state.findings if f.code == "reporting-guideline-for-design"]
    if not found and not (not state.reporting_guidelines and _stage_at_least(state, DRAFTING)):
        return []
    designs = {key: guidelines for key, _label, guidelines in state.study_types}
    names = designs.get(state.study_type) or tuple(
        sorted({name for _key, _label, guidelines in state.study_types for name in guidelines}))
    have = state.reporting_guidelines
    options = [
        Option(name, name, f"paper.yaml declares {name} beside {', '.join(have) or 'nothing'};"
               " the reporting-checklist skill then retrieves its checklist",
               argv(state, "set", "reporting_guideline", *have, name))
        for name in names if name not in have
    ]  # fmt: skip
    options.append(Option(
        "other", "Another guideline", "paper.yaml declares the guideline named",
        argv(state, "set", "reporting_guideline", *have, "<GUIDELINE>"),
        placeholders={"GUIDELINE": "the guideline's name, as STROBE or CONSORT"},
    ))  # fmt: skip
    own = designs.get(state.study_type) or ()
    recommended = own[0] if len(own) == 1 and own[0] not in have else None
    return [_choice_action(
        "choose-guideline", "Choose the reporting guideline", "reporting-checklist",
        Choice("Which reporting guideline does the paper follow?", tuple(options), recommended),
        found, state, 2)]  # fmt: skip


def _either(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def _choose_study_type(state: State) -> list[Action]:
    if state.study_type is not None or not state.study_types:
        return []
    options = tuple(
        Option(key, label, "G12 asks the plan for the sections this design needs"
               + (f", and it is reported with {_either(guidelines)}" if guidelines else ""),
               argv(state, "set", "study_type", key))
        for key, label, guidelines in state.study_types
    )  # fmt: skip
    return [_choice_action("choose-study-type", "Name the study design", "analysis-plan",
                           Choice("What kind of study is this?", options), (), state, 3)]


def _co_author_checks(state: State) -> list[Action]:
    checked = state.checker
    if checked is None or not _stage_at_least(state, INTERNAL_REVIEW):
        return []
    if not (checked.outstanding or checked.stale or checked.disagreements):
        return []
    return [Action(
        id="co-author-checks", rule="co-author-checks", tier=7,
        title=f"Co-authors' checks: {checked.outstanding} of {checked.items} unanswered, "
        f"{checked.stale} stale, {checked.disagreements} disagreed on",
        why=WHY["co-author-checks"], skill="co-author-checking",
        argv=argv(state, "checker", "status"),
    )]  # fmt: skip


def _warnings(state: State) -> list[Action]:
    by_skill: dict[str, list[Finding]] = {}
    for finding in state.findings:
        if finding.severity != WARN or finding.code in CHOICE_CODES:
            continue
        route = route_of(finding.code)
        skill = route.skill if route else None
        by_skill.setdefault(skill or f"gate:{finding.gate}", []).append(finding)
    actions = []
    for name, group in by_skill.items():
        ordered = _in_order(group, state.root)
        routes = {route_of(f.code) for f in ordered}
        commands = {r.argv for r in routes if r is not None}
        words = commands.pop() if len(commands) == 1 and None not in routes else ("check",)
        skill = None if name.startswith("gate:") else name
        if skill is None:
            skill = GATE_SKILLS.get(ordered[0].gate)
        title = (f"{len(ordered)} warning{'s' if len(ordered) != 1 else ''} for "
                 + (f"the {skill} skill" if not name.startswith("gate:") else
                    f"{ordered[0].gate}, which no route names"))  # fmt: skip
        actions.append(Action(
            id=f"warnings:{name}", rule="warnings", tier=8, title=title, why=WHY["warnings"],
            skill=skill, argv=argv(state, *words) if words else None,
            codes=tuple(sorted({f.code for f in ordered})), findings=ordered,
            key=(_rank(ordered[0].gate), name, "", 0),
        ))  # fmt: skip
    return actions


def _advance(state: State) -> list[Action]:
    if state.kind != PROJECT or _failing(state) or state.stage not in STAGES:
        return []
    if state.stage == SUBMISSION:
        return []
    following = STAGES[STAGES.index(state.stage) + 1]
    due = state.deferred.get(following, 0)
    said = f"{due} finding{'' if due == 1 else 's'} not due now would then fail"
    options = (
        Option("preview", f"See what {following} asks first",
               f"runs every gate as at {following} and writes nothing: {said}",
               argv(state, "check", "--stage", following)),
        Option("move", f"Move on to {following}", f"paper.yaml says {following}: {said}",
               argv(state, "set", "stage", following)),
    )  # fmt: skip
    return [Action(
        id="advance", rule="advance", tier=9, who=AUTHOR, title=f"Move on to {following}",
        why=WHY["advance"], skill="project-setup",
        choice=Choice(f"Nothing fails at {state.stage}. Move on to {following} "
                      f"({DESCRIPTIONS[following]})?", options,
                      "preview" if due else "move"),
    )]  # fmt: skip


def _optional(state: State) -> list[Action]:
    if state.kind != PROJECT or _failing(state) or not _stage_at_least(state, INTERNAL_REVIEW):
        return []
    latex = state.format == "latex"
    at_submission = state.stage == SUBMISSION
    steps = [
        Action(
            id="optional:review", rule="optional", tier=10, who=AUTHOR,
            title="Have the review panel read the paper", why=WHY["optional"],
            skill="review-panel", key=(0, "", "", 0),
            choice=Choice("Send the paper to the models paper.yaml's review.models names?", (
                Option("dry-run", "See what would be sent", "says which files go to which "
                       "provider and how many calls that is, and sends nothing",
                       argv(state, "review", "--run", "--dry-run")),
                Option("run", "Send it", "sends the round's remits to each provider and files "
                       "each reading; asked of the author first", argv(state, "review", "--run"),
                       who=ASK),
            ), "dry-run"),
        ),
        Action(id="optional:build", rule="optional", tier=10, title="Build the .docx",
               why=WHY["optional"], argv=argv(state, "build"), key=(2, "", "", 0)),
        Action(id="optional:package", rule="optional", tier=10,
               title="Assemble the reproducibility package", why=WHY["optional"],
               skill="submission-pack", argv=argv(state, "package"), key=(3, "", "", 0)),
        Action(
            id="optional:approve", rule="optional", tier=10, who=AUTHOR,
            title="Each author approves the paper as it stands", why=WHY["optional"],
            key=(5, "", "", 0), choice=Choice("Which author approves now? Each runs it "
                                              "themselves.", (
                Option("approve", "Approve", "records the author's approval of the manuscript "
                       "as it stands", argv(state, "approve", "--as", "<AUTHOR>"), who=AUTHOR,
                       placeholders={"AUTHOR": "the author: ORCID iD, e-mail address or name"}),
            )),
        ),
    ]  # fmt: skip
    if not latex:
        steps.append(Action(
            id="optional:checker", rule="optional", tier=10, who=AUTHOR,
            title="Send a co-author the numbers, quotes and references to confirm",
            why=WHY["optional"], skill="co-author-checking", key=(1, "", "", 0),
            choice=Choice("Which co-author is the page for?", (
                Option("build", "Write their page", "writes checks/check-<NAME>.html, one file "
                       "to send", argv(state, "checker", "build", "--for", "<NAME>"),
                       placeholders={"NAME": "the co-author the page is for"}),
            )),
        ))  # fmt: skip
    if at_submission:
        steps.append(Action(id="optional:submit", rule="optional", tier=10,
                            title="Assemble the submission pack", why=WHY["optional"],
                            skill="submission-pack", argv=argv(state, "submit"),
                            key=(4, "", "", 0)))  # fmt: skip
        if not latex:
            steps.append(Action(
                id="optional:proof", rule="optional", tier=10, who=AUTHOR,
                title="Check the journal's proof against what was sent", why=WHY["optional"],
                skill="submission-pack", key=(6, "", "", 0),
                choice=Choice("Has the proof come back?", (
                    Option("proof", "Check it", "compares the proof's numbers and names with "
                           "the document sent", argv(state, "proof", "<FILE>"),
                           placeholders={"FILE": "the proof: .pdf, .xml, .html or .txt"}),
                )),
            ))  # fmt: skip
    # Depositing the package and communicating the paper join here as their commands are
    # added (Tasks 4 and 5): each is a step an author takes once nothing fails.
    return steps


def _start(state: State) -> list[Action]:
    if state.kind not in (NO_PROJECT, AUTHORS_ONLY):
        return []
    options = []
    for name in state.candidates if state.kind == NO_PROJECT else ():
        suffix = Path(name).suffix.lower()
        if suffix == ".docx":
            options.append(Option(f"from:{name}", f"Bring {name} in from Word",
                                  "writes the project here, with the paper as "
                                  "manuscript/main.md, its tables as pipe tables",
                                  argv(state, "init", "--from", _file(state, name))))
        elif suffix == ".tex":
            options.append(Option(f"latex:{name}", f"A LaTeX project for {name}",
                                  f"writes the project here with manuscript/main.tex; then "
                                  f"move {name}'s text into it", argv(state, "init", "--latex")))
        else:
            options.append(Option(f"markdown:{name}", f"A Markdown project for {name}",
                                  f"writes the project here with manuscript/main.md; then "
                                  f"move {name}'s text into it", argv(state, "init")))
        if suffix in (".docx", ".md"):
            options.append(Option(
                f"audit:{name}", f"Only audit {name}'s numbers",
                "checks the paper's typed numbers against the analysis outputs, with the "
                "paper-audit skill, and makes no project",
                argv(state, "audit", _file(state, name), "--against", "<OUTPUTS>"),
                placeholders={"OUTPUTS": "the analysis outputs: files or folders"},
            ))  # fmt: skip
    options += [
        Option("markdown", "A new Markdown project", "writes the project here, its "
               "manuscript manuscript/main.md", argv(state, "init")),
        Option("latex", "A new LaTeX project", "writes the project here, its manuscript "
               "manuscript/main.tex", argv(state, "init", "--latex")),
    ]  # fmt: skip
    words = [name for name in state.candidates if name.lower().endswith(".docx")]
    recommended = f"from:{words[0]}" if len(words) == 1 and state.kind == NO_PROJECT else None
    if state.kind == AUTHORS_ONLY:
        title, question = ("Write paper.yaml beside authors.yaml",
                           "authors.yaml is here and paper.yaml is not: start the project?")
    else:
        title, question = "Start a manuscript-guard project", "How should the project start?"
    return [Action(id="start", rule="start", tier=1, who=AUTHOR, title=title,
                   why=WHY["start"], skill="project-setup",
                   choice=Choice(question, tuple(options), recommended))]  # fmt: skip


@dataclass(frozen=True)
class Rule:
    id: str
    tier: int
    applies: Callable[[State], bool]
    build: Callable[[State], list[Action]]


def _is_project(state: State) -> bool:
    return state.kind == PROJECT


#: The rules, in the order their tiers are decided. A rule id is part of what `next --json`
#: says, and is not renamed.
RULES: tuple[Rule, ...] = (
    Rule("cannot-check", 0, lambda s: s.kind in (PROJECT, UNREADABLE), _cannot_check),
    Rule("start", 1, lambda s: s.kind in (NO_PROJECT, AUTHORS_ONLY), _start),
    Rule("stale-results", 2, _is_project, _tiered("stale-results", 2,
                                                  "Bring the results up to date")),
    Rule("plan", 3, _is_project, _tiered("plan", 3, "Put the analysis plan right")),
    Rule("choose-journal", 4, _is_project, _choose_journal),
    Rule("choose-english", 4, _is_project, _choose_english),
    Rule("choose-guideline", 4, _is_project, _choose_guideline),
    Rule("choose-study-type", 4, _is_project, _choose_study_type),
    Rule("provenance", 5, _is_project, _tiered("provenance", 5, "Give the numbers a source")),
    Rule("failures", 6, _is_project, _tiered("failures", 6, "Put right")),
    Rule("co-author-checks", 7, _is_project, _co_author_checks),
    Rule("warnings", 8, _is_project, _warnings),
    Rule("advance", 9, _is_project, _advance),
    Rule("optional", 10, _is_project, _optional),
)  # fmt: skip


def decide(state: State) -> list[Action]:
    """What to do, in order: a pure function of `state`."""
    actions = [action for rule in RULES if rule.applies(state) for action in rule.build(state)]
    return sorted(actions, key=lambda action: (action.tier, action.key, action.id))
