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
    assert options["audit:paper.docx"] == ("audit", "paper.docx", "--against", "<OUTPUTS>")
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
    assert move.argv == ("set", "stage", "internal-review")
    assert decide(settled(tmp_path)) and decide(settled(tmp_path))[0].choice.recommended == "move"
    assert decide(settled(tmp_path, stage="submission", format="latex"))[0].rule == "optional"


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
        offered = "advance" in rules(decide(state))
        assert offered == (not failing and state.stage != "submission"), state


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
    return [re.sub(r"<[A-Z_]+>", "1", word) for word in words]


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


def _given(value: ast.expr, constants: dict[str, object]) -> set[str]:
    """The codes an expression given as a `code` can be: a string, either side of a
    conditional, or a constant of the module."""
    if isinstance(value, ast.IfExp):
        return _given(value.body, constants) | _given(value.orelse, constants)
    said = constants.get(value.id) if isinstance(value, ast.Name) else getattr(value, "value", None)
    return {said} if isinstance(said, str) and _SHAPE.fullmatch(said) else set()


def reported_codes() -> set[str]:
    """Every code the package reports, as far as reading its source says: each string given
    as a finding's `code` (by keyword, by position to a function whose parameter is `code`,
    either side of a conditional, or a constant of the module named for one), each code the
    stage policy lists, and the design rounds' codes made from the review gate's seal."""
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in SRC.rglob("*.py")}
    positions: dict[str, set[int]] = {"Finding": {1}}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [a.arg for a in node.args.args if a.arg != "self"]
                if "code" in names:
                    positions.setdefault(node.name, set()).add(names.index("code"))
    found: set[str] = set()
    for tree in trees.values():
        constants = {
            target.id: node.value.value
            for node in tree.body if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
            for target in node.targets if isinstance(target, ast.Name)
        }  # fmt: skip

        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "code":
                found |= _given(node.value, constants)
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                for index in positions.get(name, ()):
                    if index < len(node.args):
                        found |= _given(node.args[index], constants)
    seal = next(node for node in ast.walk(trees[SRC / "gates" / "review.py"])
                if isinstance(node, ast.FunctionDef) and node.name == "_check_seal")  # fmt: skip
    sealed = {node.value for node in ast.walk(seal) if isinstance(node, ast.Constant)
              and isinstance(node.value, str) and _SHAPE.fullmatch(node.value)}  # fmt: skip
    return found | set(BINDS_AT) | {f"design-{code}" for code in sealed}


def test_every_code_is_routed_or_asks_nothing() -> None:
    codes = reported_codes()
    assert len(codes) > 400, "the walk found the codes"
    assert {"design-reading-altered", "p-decision-error", "summary-not-reported"} <= codes
    unrouted = sorted(code for code in codes if route_of(code) is None and code not in NO_ACTION)
    assert unrouted == []


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


def test_the_longest_prefix_wins() -> None:
    assert route_of("journal-style-changed").argv == ("style",)
    assert route_of("journal-profile-stale").argv == ("journal",)
    assert route_of("model-artefact").skill == "manuscript-writing"
    assert route_of("model-few-events").skill == "methods-writer"


# ------------------------------------------------------------------------- on the example

VALIDATOR = Draft202012Validator(load_schema("next"))


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}  # fmt: skip


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
