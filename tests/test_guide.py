"""`manuscript-guard next`: one rule each, the order, the routes and the commands.

`decide` is a pure function of a `State`, so each rule is held on the smallest state that
calls for it. What `inspect` reads is held on copies of the example, each changed the way a
project goes wrong, and the example itself is read with nothing written.
"""

from __future__ import annotations

import ast
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from manuscript_guard import guide
from manuscript_guard.cli import build_parser, main
from manuscript_guard.contracts._schema import load_schema
from manuscript_guard.findings import FAIL, INFO, WARN, Finding
from manuscript_guard.guide import (
    AUTHORS_ONLY,
    NO_ACTION,
    NO_PROJECT,
    UNREADABLE,
    Checker,
    State,
    decide,
    route_of,
    shown,
    to_dict,
)
from manuscript_guard.guide.model import MISSING, PLACEHOLDER
from manuscript_guard.guide.routes import PERSON_ONLY
from manuscript_guard.policy import BINDS_AT, STAGES

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plugin import described_codes, skill_names  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src" / "manuscript_guard"
DESIGNS = (("cohort", "cohort study", ("STROBE", "RECORD")),
           ("trial", "randomised trial", ("CONSORT",)))  # fmt: skip


def settled(root: Path, **given) -> State:
    """A project whose four choices are made, so that only the rule under test speaks."""
    defaults = dict(root=root, cwd=root, target_journal="demo", english_variant="en-GB",
                    reporting_guidelines=("STROBE",), study_type="cohort", study_types=DESIGNS,
                    journals=("demo",))  # fmt: skip
    return State(**{**defaults, **given})


def at(root: Path, gate: str, code: str, severity: str = FAIL, file: str = "manuscript/main.md",
       line: int | None = 3) -> Finding:  # fmt: skip
    return Finding(gate=gate, code=code, message=f"{code} here", severity=severity,
                   path=root / file, line=line)  # fmt: skip


def rules(actions) -> list[str]:
    return [action.rule for action in actions]


def of(state: State, rule: str) -> list:
    """The actions of one rule, out of all `decide` says of `state`."""
    return [action for action in decide(state) if action.rule == rule]


def every_argv(actions) -> list[tuple[str, ...]]:
    found = [action.argv for action in actions if action.argv is not None]
    for action in actions:
        if action.choice is not None:
            found += [option.argv for option in action.choice.options]
    return found


# ------------------------------------------------------------------------- one per rule


def test_a_gate_that_could_not_run_comes_first(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(
        at(tmp_path, "G6", "model-artefact"), at(tmp_path, "G2", "gate-errored", line=None)))
    actions = decide(state)
    assert actions[0].rule == "cannot-check" and actions[0].tier == 0
    assert actions[0].codes == ("gate-errored",)


def test_an_unreadable_paper_yaml_is_the_one_thing_said(tmp_path: Path) -> None:
    actions = decide(State(kind=UNREADABLE, root=tmp_path, error="bad YAML", stage=None,
                           format=None))  # fmt: skip
    assert rules(actions) == ["cannot-check"]
    assert "bad YAML" in actions[0].why and actions[0].who == "author"


def test_no_project_offers_init_and_init_from(tmp_path: Path) -> None:
    state = State(kind=NO_PROJECT, root=tmp_path, cwd=tmp_path, stage=None, format=None,
                  candidates=("paper.docx", "draft.md", "thesis.tex"))  # fmt: skip
    (action,) = decide(state)
    assert action.rule == "start" and action.tier == 1
    options = {option.id: option.argv for option in action.choice.options}
    assert options["from:paper.docx"] == ("init", "--from", "paper.docx")
    assert options["latex:thesis.tex"] == ("init", "--latex")
    assert options["markdown:draft.md"] == ("init",)
    assert options["audit:paper.docx"] == ("audit", "paper.docx", "--against", "<OUTPUTS...>")
    assert action.choice.recommended == "from:paper.docx"


def test_authors_yaml_alone_offers_init(tmp_path: Path) -> None:
    (action,) = decide(State(kind=AUTHORS_ONLY, root=tmp_path, stage=None, format=None))
    assert action.rule == "start" and "authors.yaml" in action.choice.question
    assert {option.argv for option in action.choice.options} == {
        ("init", tmp_path.as_posix()), ("init", tmp_path.as_posix(), "--latex")}


def test_stale_results_come_before_what_reads_them(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(
        at(tmp_path, "G2", "unclassified-number"),
        at(tmp_path, "G1", "results-edited", file="results/a.json")))
    actions = decide(state)
    assert rules(actions)[:2] == ["stale-results", "provenance"]
    assert actions[0].skill == "results-binding" and actions[0].argv == ("verify",)


def test_the_plan_comes_after_the_results_and_before_the_numbers(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(at(tmp_path, "G2", "unclassified-number"),
                                        at(tmp_path, "G12", "no-analysis-plan", line=None),
                                        at(tmp_path, "G1", "script-newer")))  # fmt: skip
    assert rules(decide(state)) == ["stale-results", "plan", "provenance"]


def test_a_missing_profile_offers_writing_it_or_another_journal(tmp_path: Path) -> None:
    state = settled(tmp_path, target_journal="lancet", journals=("bmj",),
                    findings=(at(tmp_path, "G4", "journal-profile-missing", line=None),))
    (action,) = of(state, "choose-journal")
    assert action.skill == "journal-profile"
    assert action.choice.recommended == "profile"
    options = {option.id: option for option in action.choice.options}
    assert options["profile"].argv == ("journal", "--template", "lancet")
    # Replacing a journal is asked of the author: the guard on `set` asks it too.
    assert options["set:bmj"].argv == ("set", "target_journal", "bmj")
    assert options["set:bmj"].who == "ask-author"


def test_no_journal_from_drafting_offers_the_journals_there_are(tmp_path: Path) -> None:
    state = settled(tmp_path, target_journal=None, journals=("bmj",))
    (action,) = of(state, "choose-journal")
    assert action.choice.recommended == "set:bmj"
    assert [option.id for option in action.choice.options] == ["set:bmj", "new"]
    assert of(settled(tmp_path, target_journal=None, stage="analysis"), "choose-journal") == []


def test_the_english_offered_first_is_the_journals(tmp_path: Path) -> None:
    state = settled(tmp_path, english_variant=None, journal_english="en-US")
    (action,) = of(state, "choose-english")
    assert action.choice.recommended == "en-US"
    assert {option.argv for option in action.choice.options} == {
        ("set", "english_variant", "en-GB"), ("set", "english_variant", "en-US")}


def test_the_guideline_offered_is_the_designs(tmp_path: Path) -> None:
    state = settled(tmp_path, reporting_guidelines=(), study_type="trial")
    (action,) = of(state, "choose-guideline")
    assert action.choice.recommended == "CONSORT"
    assert action.choice.options[0].argv == ("set", "reporting_guideline", "CONSORT")
    # One the paper declares is kept beside the one added.
    state = settled(tmp_path, study_type="trial", findings=(
        at(tmp_path, "G8r", "reporting-guideline-for-design", WARN, line=None),))
    (action,) = of(state, "choose-guideline")
    assert action.choice.options[0].argv == ("set", "reporting_guideline", "STROBE", "CONSORT")


def test_an_undeclared_design_offers_each_design(tmp_path: Path) -> None:
    (action,) = of(settled(tmp_path, study_type=None, stage="design"), "choose-study-type")
    assert action.choice.recommended is None
    assert [option.argv for option in action.choice.options] == [
        ("set", "study_type", "cohort"), ("set", "study_type", "trial")]


def test_the_choices_come_in_their_order(tmp_path: Path) -> None:
    state = settled(tmp_path, target_journal=None, english_variant=None,
                    reporting_guidelines=(), study_type=None)  # fmt: skip
    assert rules(decide(state)) == ["choose-journal", "choose-english", "choose-guideline",
                                    "choose-study-type", "advance"]  # fmt: skip


def test_a_number_one_value_reads_as_is_bound_by_its_own_command(tmp_path: Path) -> None:
    state = settled(tmp_path, bindable={"manuscript/main.md:3": "{{results.n}}"}, findings=(
        at(tmp_path, "G2", "unclassified-number"),
        at(tmp_path, "G2", "unclassified-number", line=9)))
    first, rest = decide(state)
    assert first.id == "provenance:bind:manuscript/main.md:3" and first.who == "ask-author"
    assert first.argv == ("bind", "--apply", "--only", "manuscript/main.md:3")
    assert rest.id == "provenance:unclassified-number" and rest.argv == ("bind",)
    assert rest.count == 1


def test_another_failure_goes_to_its_codes_skill(tmp_path: Path) -> None:
    (action,) = decide(settled(tmp_path, findings=(at(tmp_path, "G6", "model-artefact"),)))
    assert (action.rule, action.tier, action.skill) == ("failures", 6, "manuscript-writing")


def test_a_code_no_route_names_goes_to_its_gate(tmp_path: Path) -> None:
    (action,) = decide(settled(tmp_path, findings=(at(tmp_path, "G9", "never-heard-of"),)))
    assert action.skill == "methods-writer" and action.argv == ("check",)
    assert "No route names never-heard-of" in action.why


def test_an_open_round_of_checks_is_named_from_internal_review(tmp_path: Path) -> None:
    state = settled(tmp_path, stage="internal-review", checker=Checker(10, 2, 1, 0))
    action = next(a for a in decide(state) if a.rule == "co-author-checks")
    assert action.tier == 7 and action.argv == ("checker", "status")
    assert "2 of 10" in action.title
    assert not [a for a in decide(settled(tmp_path, checker=Checker(10, 2, 1, 0)))
                if a.rule == "co-author-checks"]  # drafting  # fmt: skip


def test_warnings_are_one_action_per_skill(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(
        at(tmp_path, "G14", "spelling-variant", WARN), at(tmp_path, "G6", "ai-phrasing", WARN),
        at(tmp_path, "G10", "figure-review-finding", WARN)))
    warned = [a for a in decide(state) if a.rule == "warnings"]
    assert sorted(a.skill for a in warned) == ["figure-review", "manuscript-writing"]
    writing = next(a for a in warned if a.skill == "manuscript-writing")
    assert writing.codes == ("ai-phrasing", "spelling-variant") and writing.count == 2


def test_moving_on_is_offered_when_nothing_fails(tmp_path: Path) -> None:
    state = settled(tmp_path, deferred={"internal-review": 3})
    (action,) = decide(state)
    assert action.rule == "advance" and action.choice.recommended == "preview"
    preview, move = action.choice.options
    assert preview.argv == ("check", "--stage", "internal-review")
    assert "3 findings" in preview.effect
    assert move.argv == ("set", "stage", "internal-review") and move.who == "ask-author"
    assert decide(settled(tmp_path)) and decide(settled(tmp_path))[0].choice.recommended == "move"
    assert decide(settled(tmp_path, stage="submission", format="latex"))[0].rule == "optional"


def test_a_view_of_an_earlier_stage_moves_nothing(tmp_path: Path) -> None:
    """paper.yaml says submission, and `next --stage drafting` is a view of drafting: no
    `set stage internal-review`, which would move the paper back."""
    view = settled(tmp_path, stage="drafting", declared_stage="submission")
    assert of(view, "advance") == []
    assert not [w for w in every_argv(decide(view)) if w[:2] == ("set", "stage")]
    assert of(settled(tmp_path, stage="drafting", declared_stage="internal-review"),
              "advance") == []  # fmt: skip
    # A view of a later stage moves from the declared one, never past the next.
    (ahead,) = of(settled(tmp_path, stage="internal-review", declared_stage="drafting"),
                  "advance")  # fmt: skip
    assert ahead.choice.options[1].argv == ("set", "stage", "internal-review")


def test_the_english_replaced_is_asked_of_the_author(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(
        at(tmp_path, "G4", "english-variant-mismatch", line=None),))
    (action,) = of(state, "choose-english")
    assert [(o.id, o.who) for o in action.choice.options] == [("en-US", "ask-author")]
    (first,) = of(settled(tmp_path, english_variant=None), "choose-english")
    assert {o.who for o in first.choice.options} == {"agent"}


def test_a_warning_with_a_command_and_no_skill_names_the_command(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(at(tmp_path, "G1", "document-stale", WARN),))
    (action,) = of(state, "warnings")
    assert action.skill is None and action.argv == ("build",)
    assert "manuscript-guard build" in action.title and "no route" not in action.title


def test_the_command_shown_is_quoted_for_the_prompt_it_is_typed_at() -> None:
    words = ("audit", "C:/My papers/a.docx", "--against", "<OUTPUTS...>")
    assert shown(words, windows=True) == (
        'manuscript-guard audit "C:/My papers/a.docx" --against <OUTPUTS...>')
    assert shown(words, windows=False) == (
        "manuscript-guard audit 'C:/My papers/a.docx' --against <OUTPUTS...>")


def test_a_word_cmd_exe_would_split_is_quoted_and_one_it_cannot_take_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Round 2: `C:/R&D/p` was shown bare, and cmd.exe ran `D/p` as a second command."""
    for word in ("C:/R&D/p", "a|b", "a<b", "a>b", "a^b", "f(1)", "a\tb"):
        assert shown(("check", word), windows=True) == f'manuscript-guard check "{word}"'
    assert shown(("check", "C:/a b" + chr(92)), windows=True) == (
        'manuscript-guard check "C:/a b' + chr(92) * 2 + '"')
    # `%` is left as it is (a known gap), and a `"` alone is escaped as list2cmdline does.
    assert shown(("check", "C:/100%/p"), windows=True) == "manuscript-guard check C:/100%/p"
    assert shown(("set", "x", 'a"b'), windows=True) == "manuscript-guard set x a" + chr(92) + '"b'
    # A word holding `"` beside a metacharacter is a value no quoting gives cmd.exe safely.
    refused = ("set", "reporting_guideline", 'R"&D')
    assert shown(refused, windows=True) is None
    assert shown(refused, windows=False) is not None
    from manuscript_guard.guide import model, say

    monkeypatch.setattr(say, "shown", lambda words: model.shown(words, windows=True))
    state = settled(tmp_path, reporting_guidelines=('R"&D',), findings=(
        at(tmp_path, "G5", "reporting-guideline-for-design", line=None),))
    actions = decide(state)
    text = say.render(state, actions, every=True)
    assert "which cmd.exe cannot be given safely" in text
    assert "manuscript-guard set reporting_guideline" not in text
    VALIDATOR.validate(say.to_dict(state, actions))


def test_the_text_says_which_actions_are_the_authors(tmp_path: Path) -> None:
    """Round 2: an author's action printed its title, reason and skill, and only options
    said who runs them."""
    from manuscript_guard.guide.say import render

    state = settled(tmp_path, findings=(
        at(tmp_path, "G7", "attestation-not-human"),
        at(tmp_path, "G11", "open-major-finding", file="review/panel-1.yaml")))
    text = render(state, decide(state), every=True)
    assert "the author decides it, or runs it" in text  # no command
    assert "run: manuscript-guard review  (the author runs it)" in text
    agents = settled(tmp_path, findings=(at(tmp_path, "G6", "model-artefact"),))
    assert "author" not in render(agents, decide(agents), every=True).split("\n", 3)[3]


def test_an_earlier_view_with_nothing_to_do_says_it_is_a_view(tmp_path: Path) -> None:
    from manuscript_guard.guide.say import render

    view = settled(tmp_path, stage="drafting", declared_stage="submission")
    assert decide(view) == []
    assert "Nothing to do at this view" in render(view, [])
    assert "Nothing to do: every gate" in render(settled(tmp_path, stage="submission"), [])


def test_the_optional_steps_are_those_the_tool_has(tmp_path: Path) -> None:
    ids = {a.id for a in decide(settled(tmp_path, stage="internal-review"))}
    assert ids == {"advance", "optional:review", "optional:checker", "optional:build",
                   "optional:package", "optional:approve"}
    ids = {a.id for a in decide(settled(tmp_path, stage="submission"))}
    assert {"optional:submit", "optional:proof"} <= ids and "advance" not in ids
    # A LaTeX manuscript: the checker and proof read only Markdown.
    ids = {a.id for a in decide(settled(tmp_path, stage="submission", format="latex"))}
    assert "optional:checker" not in ids and "optional:proof" not in ids


# ------------------------------------------------------------------------- properties

_CODES = (("G1", "results-edited"), ("G12", "plan-section-missing"),
          ("G2", "unclassified-number"), ("G7", "quote-not-in-source"),
          ("G6", "model-artefact"), ("G14", "spelling-variant"), ("G4", "journal-profile-missing"),
          ("G0", "gate-errored"), ("G9", "methods-drift"), ("G11", "no-review"))  # fmt: skip


def drawn(rng: random.Random, root: Path) -> State:
    findings = tuple(
        at(root, gate, code, rng.choice((FAIL, WARN, INFO)),
           file=f"manuscript/{rng.randint(1, 3)}.md", line=rng.randint(1, 40))
        for gate, code in rng.sample(_CODES, rng.randint(0, len(_CODES)))
        for _ in range(rng.randint(1, 3))
    )  # fmt: skip
    return settled(
        root, stage=rng.choice(STAGES), findings=findings,
        declared_stage=rng.choice((None, *STAGES)),
        format=rng.choice(("markdown", "latex")),
        deferred={stage: rng.randint(1, 4) for stage in rng.sample(STAGES, rng.randint(0, 2))},
        target_journal=rng.choice((None, "demo")), english_variant=rng.choice((None, "en-GB")),
        checker=rng.choice((None, Checker(5, 1, 0, 1))),
    )  # fmt: skip


def test_the_order_of_the_findings_changes_nothing(tmp_path: Path) -> None:
    rng = random.Random(7)
    for _ in range(40):
        state = drawn(rng, tmp_path)
        before = to_dict(state, decide(state))
        shuffled = list(state.findings)
        rng.shuffle(shuffled)
        again = State(**{**vars(state), "findings": tuple(shuffled)})
        assert to_dict(again, decide(again)) == before


def test_moving_on_is_offered_exactly_when_nothing_fails(tmp_path: Path) -> None:
    rng = random.Random(11)
    for _ in range(200):
        state = drawn(rng, tmp_path)
        failing = any(f.severity == FAIL for f in state.findings)
        declared = state.declared_stage or state.stage
        behind = STAGES.index(state.stage) < STAGES.index(declared)
        offered = "advance" in rules(decide(state))
        assert offered == (not failing and declared != "submission" and not behind), state
        # Never a move back, and never further than the stage after the declared one.
        moves = [w[2] for w in every_argv(decide(state)) if w[:2] == ("set", "stage")]
        assert all(STAGES.index(m) == STAGES.index(declared) + 1 for m in moves), state


def test_the_optional_steps_come_only_once_nothing_fails_from_internal_review(
    tmp_path: Path,
) -> None:
    rng = random.Random(13)
    for _ in range(200):
        state = drawn(rng, tmp_path)
        failing = any(f.severity == FAIL for f in state.findings)
        late = STAGES.index(state.stage) >= STAGES.index("internal-review")
        assert ("optional" in rules(decide(state))) == (late and not failing), state


def _filled(words: tuple[str, ...]) -> list[str]:
    """Each placeholder filled: `<NAME>` with one word, `<NAME...>` with two."""
    filled: list[str] = []
    for word in words:
        held = PLACEHOLDER.fullmatch(word)
        filled += (["1", "2"] if held.group(2) else ["1"]) if held else [word]
    return filled


def test_every_command_offered_parses(tmp_path: Path) -> None:
    rng = random.Random(17)
    states = [drawn(rng, tmp_path) for _ in range(60)]
    states += [State(kind=NO_PROJECT, root=tmp_path, stage=None, format=None,
                     candidates=("a b.docx", "c.md", "d.tex")),
               State(kind=AUTHORS_ONLY, root=tmp_path, stage=None, format=None),
               State(kind=UNREADABLE, root=tmp_path, stage=None, format=None, error="x"),
               settled(tmp_path, cwd=None, stage="submission", target_journal=None,
                       english_variant=None, reporting_guidelines=(), study_type=None,
                       bindable={"manuscript/main.md:3": "{{results.n}}"},
                       findings=(at(tmp_path, "G2", "unclassified-number", FAIL),))]  # fmt: skip
    parser = build_parser()
    seen = set()
    for state in states:
        for words in every_argv(decide(state)):
            seen.add(words[0])
            parser.parse_args(_filled(words))
            assert shown(words).startswith("manuscript-guard " + words[0])
    assert {"init", "audit", "set", "check", "bind", "review", "checker", "approve", "proof",
            "journal", "verify", "submit", "build", "package"} <= seen


def test_a_command_names_the_folder_where_next_was_run_elsewhere(tmp_path: Path) -> None:
    elsewhere = settled(tmp_path, cwd=tmp_path / "other", findings=(
        at(tmp_path, "G1", "results-edited"),))
    assert decide(elsewhere)[0].argv == ("verify", tmp_path.as_posix())
    (choice,) = of(settled(tmp_path, cwd=None, english_variant=None), "choose-english")
    assert choice.choice.options[0].argv[-2:] == ("--path", tmp_path.as_posix())


# ------------------------------------------------------------------------- the routes


_SHAPE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+")
#: The fixed start of a code an f-string makes: `f"design-{f.code}"`.
_PREFIX = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*-")


@dataclass
class _Walk:
    """What the walk of the source found: the codes, and the prefixes of codes made at run
    time, with where each code-taking function takes its `code`."""

    codes: set[str] = field(default_factory=set)
    prefixes: set[str] = field(default_factory=set)
    positions: dict[str, set[int]] = field(default_factory=lambda: {"Finding": {1}})
    #: What each function returns, by place in a returned tuple (-1 for a bare value).
    returns: dict[str, dict[int, list[ast.expr]]] = field(default_factory=dict)


def _strings(value: ast.expr, names: dict[str, list[ast.expr]], walk: _Walk,
             depth: int = 0) -> None:  # fmt: skip
    """Add the codes `value` can be to `walk`: a string, either side of a conditional, a name
    bound to one in the function or the module, an element of a tuple a helper returns, or
    the fixed start of an f-string."""
    if depth > 6:
        return
    if isinstance(value, ast.IfExp):
        for side in (value.body, value.orelse):
            _strings(side, names, walk, depth + 1)
    elif isinstance(value, ast.Constant) and isinstance(value.value, str):
        if _SHAPE.fullmatch(value.value):
            walk.codes.add(value.value)
    elif isinstance(value, ast.JoinedStr) and value.values:
        first = value.values[0]
        fixed = _PREFIX.match(first.value) if isinstance(first, ast.Constant) else None
        if fixed:
            walk.prefixes.add(fixed.group())
    elif isinstance(value, ast.Name):
        for bound in names.get(value.id, ()):
            _strings(bound, names, walk, depth + 1)


def _called(call: ast.expr) -> str | None:
    if not isinstance(call, ast.Call):
        return None
    return getattr(call.func, "id", None) or getattr(call.func, "attr", None)


def _bindings(scope: ast.AST, walk: _Walk) -> dict[str, list[ast.expr]]:
    """Each name the scope binds, with what it may be bound to: an assignment, one place of a
    tuple unpacked from a tuple or from a helper's return, or one place of the items of a
    loop over a literal list or tuple."""
    names: dict[str, list[ast.expr]] = {}

    def bind(target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            names.setdefault(target.id, []).append(value)
            for held in walk.returns.get(_called(value) or "", {}).get(-1, ()):
                names[target.id].append(held)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
                for part, held in zip(target.elts, value.elts, strict=True):
                    bind(part, held)
            for index, part in enumerate(target.elts):
                for held in walk.returns.get(_called(value) or "", {}).get(index, ()):
                    bind(part, held)

    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, node.value)
        elif isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            for item in node.iter.elts:
                bind(node.target, item)
    return names


def _returns(tree: ast.AST, walk: _Walk) -> None:
    """Where each function takes its `code`, and what it returns, by place."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = [a.arg for a in node.args.args if a.arg != "self"]
        if "code" in names:
            walk.positions.setdefault(node.name, set()).add(names.index("code"))
        held = walk.returns.setdefault(node.name, {})
        for returned in ast.walk(node):
            if not isinstance(returned, ast.Return) or returned.value is None:
                continue
            if isinstance(returned.value, ast.Tuple):
                for index, part in enumerate(returned.value.elts):
                    held.setdefault(index, []).append(part)
            else:
                held.setdefault(-1, []).append(returned.value)


def reported_codes() -> _Walk:
    """Every code the package reports, as far as reading its source says: each value given
    as a finding's `code`, by keyword or by position to a function whose parameter is `code`,
    read through `_strings`; each code the stage policy lists; and the design rounds' codes
    made from the review gate's seal. A code made at run time leaves its fixed start."""
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in SRC.rglob("*.py")}
    walk = _Walk()
    for tree in trees.values():
        _returns(tree, walk)
    for tree in trees.values():
        top = ast.Module(body=[n for n in tree.body if isinstance(n, ast.Assign)], type_ignores=[])
        module = _bindings(top, walk)
        scopes = [node for node in ast.walk(tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]  # fmt: skip
        for scope in [tree, *scopes]:
            names = {**module, **(_bindings(scope, walk) if scope is not tree else {})}
            for node in ast.walk(scope):
                if isinstance(node, ast.keyword) and node.arg == "code":
                    _strings(node.value, names, walk)
                for index in walk.positions.get(_called(node) or "", ()):
                    if index < len(node.args):
                        _strings(node.args[index], names, walk)
    seal = next(node for node in ast.walk(trees[SRC / "gates" / "review.py"])
                if isinstance(node, ast.FunctionDef) and node.name == "_check_seal")  # fmt: skip
    sealed = {node.value for node in ast.walk(seal) if isinstance(node, ast.Constant)
              and isinstance(node.value, str) and _SHAPE.fullmatch(node.value)}  # fmt: skip
    walk.codes |= set(BINDS_AT) | {f"design-{code}" for code in sealed}
    return walk


def _routed(code: str) -> bool:
    return route_of(code) is not None or code in NO_ACTION


def test_every_code_is_routed_or_asks_nothing() -> None:
    walk = reported_codes()
    assert len(walk.codes) > 400, "the walk found the codes"
    # Through a module constant, a conditional, a local name, a tuple unpacked.
    assert {"design-reading-altered", "p-decision-error", "summary-not-reported",
            "file-lost", "figure-line-thin", "claim-moved"} <= walk.codes  # fmt: skip
    assert sorted(code for code in walk.codes if not _routed(code)) == []
    # A code made at run time is routed by the prefix it is made with.
    assert "design-" in walk.prefixes
    assert sorted(prefix for prefix in walk.prefixes if route_of(prefix + "x") is None) == []


def test_every_person_only_code_is_the_authors() -> None:
    """An agent may draft these; only the person the hint names signs, judges, attests,
    approves or reads, and an agent that wrote the name would pass the gate."""
    listed = {"attestation-not-human", "attestation-thin", "judgement-not-human",
              "similar-decision-not-human", "data-source-not-a-person",
              "design-override-unsigned", "figures-not-seen", "journal-manual-unsigned",
              "approval-missing", "approval-stale",
              # Round 2: a finding left as it stands records who decided (`overridden_by`).
              "comment-unanswered", "open-major-finding", "design-major-open"}  # fmt: skip
    assert listed == PERSON_ONLY
    assert {code: route_of(code).who for code in listed} == dict.fromkeys(listed, "author")
    assert listed <= reported_codes().codes


def test_a_person_only_failure_and_warning_are_the_authors(tmp_path: Path) -> None:
    state = settled(tmp_path, findings=(
        at(tmp_path, "G7", "attestation-not-human"),
        at(tmp_path, "G12", "similar-decision-not-human", WARN)))
    by_rule = {action.rule: action for action in decide(state)}
    assert by_rule["provenance"].who == "author"
    assert by_rule["warnings"].who == "author"


def test_a_code_a_skill_says_it_answers_goes_to_that_skill() -> None:
    wrong = {
        (name, code): getattr(route_of(code), "skill", None)
        for name in sorted(skill_names())
        for code in described_codes(name)
        if getattr(route_of(code), "skill", None) != name
    }
    assert wrong == {}


def test_a_route_names_a_skill_there_is_and_a_command_that_parses() -> None:
    parser = build_parser()
    for key, route in guide.ROUTES.items():
        assert route.skill is None or route.skill in skill_names(), key
        if route.argv is not None:
            parser.parse_args(list(route.argv))


def test_what_a_contract_refuses_is_not_sent_to_bind(tmp_path: Path) -> None:
    """Round 2: `duplicate-` sent a key the ledger and attested.yaml both define, and the
    results' own duplicates, to `bind`, which does nothing for either."""
    state = settled(tmp_path, findings=(
        at(tmp_path, "G0", "duplicate-key", file="literature/attested.yaml", line=None),
        at(tmp_path, "G0", "duplicate-key", file="results/a.json", line=None),
        at(tmp_path, "G0", "no-display", file="literature/ledger.yaml", line=None),
        at(tmp_path, "G0", "duplicate-table", file="results/a.json", line=None)))
    found = {(a.id, a.skill, a.argv) for a in decide(state) if a.rule != "advance"}
    assert found == {
        ("cannot-check:duplicate-key:literature-verify", "literature-verify", ("check",)),
        ("cannot-check:duplicate-key", "results-binding", ("check",)),
        ("failures:no-display:literature-verify", "literature-verify", ("check",)),
        ("failures:duplicate-table", "results-binding", ("check",)),
    }
    # Each code a prefix caught by accident, routed where the work is done.
    assert {code: (route_of(code).skill, route_of(code).argv) for code in (
        "duplicate-step", "duplicate-model", "variable-declared-twice", "bound-dangling",
        "bound-duplicated", "bound-uncheckable", "front-matter-unreadable",
        "front-matter-abstract", "reference-uncited", "reference-duplicate",
        "reference-title-duplicate")} == {
        "duplicate-step": ("results-binding", ("check",)),
        "duplicate-model": ("results-binding", ("check",)),
        "variable-declared-twice": ("results-binding", ("check",)),
        "bound-dangling": ("results-binding", ("check",)),
        "bound-duplicated": ("results-binding", ("check",)),
        "bound-uncheckable": ("results-binding", ("check",)),
        "front-matter-unreadable": ("project-setup", ("check",)),
        "front-matter-abstract": ("manuscript-writing", None),
        "reference-uncited": ("literature-verify", ("sync-bib",)),
        "reference-duplicate": ("literature-verify", None),
        "reference-title-duplicate": ("literature-verify", None),
    }  # fmt: skip


def test_a_round_with_disagreements_or_stale_answers_is_the_authors(tmp_path: Path) -> None:
    def who(checker: Checker) -> str:
        state = settled(tmp_path, stage="internal-review", checker=checker)
        return next(a for a in decide(state) if a.rule == "co-author-checks").who

    assert (who(Checker(10, 2, 0, 0)), who(Checker(10, 0, 1, 0)), who(Checker(10, 0, 0, 1))
            ) == ("agent", "author", "author")  # fmt: skip


def test_the_longest_prefix_wins() -> None:
    assert route_of("journal-style-changed").argv == ("style",)
    assert route_of("journal-profile-stale").argv == ("journal",)
    assert route_of("model-artefact").skill == "manuscript-writing"
    assert route_of("model-few-events").skill == "methods-writer"


# ------------------------------------------------------------------------- on the example

VALIDATOR = Draft202012Validator(load_schema("next"))


def tree_bytes(root: Path) -> dict[str, tuple]:
    """Every path under `root`, folders included, with its size, its time of change and, for a
    file, its bytes: a folder added or a file rewritten with the same bytes is seen too."""
    found = {}
    for path in sorted([root, *root.rglob("*")]):
        held = path.stat()
        found[path.relative_to(root).as_posix()] = (
            path.is_dir(), held.st_size, held.st_mtime_ns,
            None if path.is_dir() else path.read_bytes())
    return found


def test_next_on_the_example_writes_nothing_and_its_json_is_the_schemas(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tree_bytes(project)
    assert main(["next", str(project), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert main(["next", str(project), "--all"]) == 0
    text = capsys.readouterr().out
    assert tree_bytes(project) == before
    assert sorted(VALIDATOR.iter_errors(said), key=str) == []
    assert said["project"] == {"kind": "project", "format": "markdown", "error": None}
    assert said["stage"]["current"] == "drafting" and said["stage"]["next"] == "internal-review"
    assert said["counts"]["fail"] == 0 and said["checker"] is None
    rules_said = [action["rule"] for action in said["actions"]]
    assert "advance" in rules_said and "optional" not in rules_said
    for action in said["actions"]:
        assert action["title"] in text
    parser = build_parser()
    for action in said["actions"]:
        words = [action["argv"]] if action["argv"] else []
        words += [option["argv"] for option in (action["choice"] or {}).get("options", ())]
        for argv in words:
            parser.parse_args(_filled(tuple(argv)))


@pytest.mark.parametrize("kind", ["none", "authors-only", "unreadable"])
def test_what_is_said_where_there_is_no_project_is_the_schemas(
    tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "paper.docx").write_bytes(b"")
    if kind == "authors-only":
        (tmp_path / "authors.yaml").write_text("authors: []\n", encoding="utf-8")
    if kind == "unreadable":
        (tmp_path / "paper.yaml").write_text("stage: [unclosed\n", encoding="utf-8")
    before = tree_bytes(tmp_path)
    assert main(["next", str(tmp_path), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert tree_bytes(tmp_path) == before
    assert sorted(VALIDATOR.iter_errors(said), key=str) == []
    assert said["project"]["kind"] == kind
    assert [action["rule"] for action in said["actions"]] == (
        ["cannot-check"] if kind == "unreadable" else ["start"])


def _paper(root: Path, old: str, new: str) -> None:
    path = root / "paper.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_edited_results_lead_to_tier_2(project: Path) -> None:
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["display"] = "9.99"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    actions = decide(guide.inspect(project))
    assert actions[0].rule == "stale-results" and actions[0].tier == 2
    assert "results-edited" in actions[0].codes
    assert "advance" not in rules(actions)


def test_a_removed_english_gives_the_english_choice(project: Path) -> None:
    _paper(project, "english_variant: en-GB\n", "")
    action = next(a for a in decide(guide.inspect(project)) if a.rule == "choose-english")
    assert action.choice.recommended == "en-GB"
    assert "english-variant-undeclared" in action.codes


def test_a_deleted_profile_gives_the_journal_choice(project: Path) -> None:
    (project / "profiles" / "journals" / "demo-journal.yaml").unlink()
    action = next(a for a in decide(guide.inspect(project)) if a.rule == "choose-journal")
    assert action.choice.recommended == "profile"
    assert action.codes == ("journal-profile-missing",)


def test_an_emptied_guideline_gives_the_checklist_choice(project: Path) -> None:
    _paper(project, "reporting_guideline:\n  - DEMO-OBS\n", "reporting_guideline: []\n")
    state = guide.inspect(project)
    assert state.reporting_guidelines == ()
    action = next(a for a in decide(state) if a.rule == "choose-guideline")
    assert action.choice.options[-1].id == "other"


def test_an_open_round_of_checks_is_read_and_left_as_it_was(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = project / "checks" / "decisions.csv"
    record.parent.mkdir()
    record.write_text("when,by,id,group,title,status,note,digest,bundle\n"
                      "2026-10-28,Ada,gone,values,Gone,ok,,,\n", encoding="utf-8")  # fmt: skip
    before = tree_bytes(project)
    state = guide.inspect(project, stage="internal-review")
    assert capsys.readouterr() == ("", "")
    assert tree_bytes(project) == before
    assert state.checker is not None and state.checker.items > 0
    assert state.checker.outstanding == state.checker.items
    said = to_dict(state, decide(state))
    assert sorted(VALIDATOR.iter_errors(said), key=str) == []
    assert said["checker"]["outstanding"] == state.checker.items
    assert "co-author-checks" in [action["rule"] for action in said["actions"]]


def test_a_path_that_is_not_there_is_said_and_nothing_offered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "paper.docx").write_bytes(b"")
    assert main(["next", str(tmp_path / "papr"), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert sorted(VALIDATOR.iter_errors(said), key=str) == []
    assert said["project"]["kind"] == MISSING and "does not exist" in said["project"]["error"]
    assert said["actions"] == []
    assert main(["next", str(tmp_path / "papr")]) == 0
    assert "does not exist" in capsys.readouterr().out


def test_a_repositorys_own_notes_are_no_paper(tmp_path: Path) -> None:
    for name in ("README.md", "readme.de.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "NEWS.md",
                 "HISTORY.md", "TODO.md", "CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md",
                 "GEMINI.md", "LICENSE.md", "Licence.md", "CHANGELOG.md", "draft.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert guide.inspect(tmp_path).candidates == ("draft.md",)


@pytest.mark.parametrize("broken", ["cp1252", "authors"])
def test_what_cannot_be_read_of_a_round_is_a_note_and_next_still_decides(
    project: Path, broken: str, capsys: pytest.CaptureFixture[str]
) -> None:
    record = project / "checks" / "decisions.csv"
    record.parent.mkdir()
    header = "when,by,id,group,title,status,note,digest,bundle\n"
    if broken == "cp1252":
        record.write_bytes((header + "2026-10-28,Ren\u00e9e,x,values,Caf\u00e9,ok,,,\n")
                           .encode("cp1252"))
    else:
        record.write_text(header, encoding="utf-8")
        (project / "authors.yaml").write_text("- just a list\n", encoding="utf-8")
    assert main(["next", str(project), "--json", "--stage", "internal-review"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert sorted(VALIDATOR.iter_errors(said), key=str) == []
    assert said["checker"] is None
    assert any("co-authors' checks stand could not be read" in note for note in said["notes"])


def _codes_of(root: Path, stage: str) -> set[str]:
    from manuscript_guard.cli import _run_gates

    report, *_ = _run_gates(root, stage=stage)
    return {finding.code for finding in report.findings}


def test_every_code_the_gates_report_here_is_routed(
    project: Path, tmp_path: Path
) -> None:
    """What the walk of the source cannot find, the gates say when run: the example at
    submission, an empty project of each format, and the example with its results edited,
    its English, its profile and its guideline taken away."""
    seen = _codes_of(project, "submission")
    for latex in (False, True):
        root = tmp_path / f"empty-{latex}"
        assert main(["init", str(root), *(["--latex"] if latex else [])]) == 0
        seen |= _codes_of(root, "submission")
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["display"] = "9.99"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    _paper(project, "english_variant: en-GB\n", "")
    _paper(project, "reporting_guideline:\n  - DEMO-OBS\n", "reporting_guideline: []\n")
    (project / "profiles" / "journals" / "demo-journal.yaml").unlink()
    seen |= _codes_of(project, "submission")
    assert len(seen) > 20
    assert sorted(code for code in seen if not _routed(code)) == []
