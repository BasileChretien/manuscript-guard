"""`manuscript-guard setup`: a project started from the authors' answers, exactly as given.

`questions` says what is still open and writes nothing; `apply` writes the project from
`design/setup.yaml` once nothing is, each setting only where it is blank, and refuses the
whole of it, with the files as they were, where any part cannot be written.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from manuscript_guard.cli import main
from manuscript_guard.contracts._schema import load_schema
from manuscript_guard.setup import apply_answers, ask, load_answers, read_folder
from manuscript_guard.setup.answers import ANSWERS_FILE, orcid_ok
from manuscript_guard.setup.questions import QUESTIONS
from manuscript_guard.setup.say import applied_dict, asked_dict
from manuscript_guard.setup.tools import prerequisites

ADA = {
    "given": "Ada",
    "family": "Byron",
    "affiliations": ["Department of Pharmacology, University of Examples, Caen, France"],
    "corresponding": True,
    "orcid": "0000-0002-1825-0097",
    "email": "ada@example.org",
}
CHARLES = {
    "given": "Zoë",
    "family": "O'Neil",
    "affiliations": ["Department of Pharmacology, University of Examples, Caen, France",
                     "Unit #2: Biostatistics, Hospital, Nagoya, Japan"],  # fmt: skip
}
#: Every question answered, with nothing that needs git or R to be written.
ANSWERS = {
    "schema": "manuscript-guard/setup/1",
    "start": "markdown",
    "title": "Statins and liver injury: a cohort study",
    "language": "en-GB",
    "study_type": "cohort",
    "reporting_guideline": ["STROBE", "RECORD"],
    "journal": {"name": "BMJ Open"},
    "authors": [ADA, CHARLES],
    "declarations": "later",
    "statistician": "O'Neil",
    "ethics_lead": "later",
    "analysis": "python",
    "data": {"where": "project", "folder": "data", "publishable": False},
    "registration": ["NCT01234567"],
    "repository": {"git": False, "visibility": "none"},
    "earlier_work": False,
}


def answered(root: Path, answers: dict) -> Path:
    path = root / ANSWERS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(answers, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")  # fmt: skip
    return path


def asked(root: Path):
    folder = read_folder(root)
    return ask(folder, load_answers(folder.root))


def files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def settings(root: Path) -> dict:
    return yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))


def no_git(root: Path) -> Path:
    """A folder with a `.git` file of its own, so that no repository above it is taken for
    the project's, and `repository.git` is not asked."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------- questions


def test_an_empty_folder_is_asked_each_question_in_order(tmp_path: Path) -> None:
    found = asked(no_git(tmp_path / "paper"))
    assert [q.id for q in found.questions] == [
        "start", "title", "language", "study_type", "journal", "authors", "analysis",
        "data.where", "registration", "repository.visibility", "earlier_work",
    ]  # fmt: skip
    assert dict(found.waiting) == {
        "reporting_guideline": ("study_type",), "declarations": ("authors",),
        "statistician": ("authors",), "ethics_lead": ("authors",),
        "data.folder": ("data.where",), "data.publishable": ("data.where",),
        "data.minimum_cell_count": ("data.where",),
        "repository.sources_in_git": ("repository.visibility",),
        "repository.github_actions": ("repository.visibility",),
    }  # fmt: skip
    assert not found.ready
    assert all(q.problem is None for q in found.questions)


def test_questions_writes_nothing(tmp_path: Path, capsys) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {"schema": "manuscript-guard/setup/1", "language": "en-US"})
    before = files(root)
    assert main(["setup", "questions", str(root), "--json"]) == 0
    assert files(root) == before
    said = json.loads(capsys.readouterr().out)
    Draft202012Validator(load_schema("setup-questions")).validate(said)
    assert "language" not in [q["id"] for q in said["questions"]]


def test_a_word_paper_in_the_folder_is_offered_and_recommended(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    (root / "paper.docx").write_bytes(b"")
    start = asked(root).questions[0]
    assert start.id == "start"
    assert [o.value for o in start.options] == ["paper.docx", "markdown", "latex"]
    assert start.recommended == "paper.docx"


@pytest.mark.parametrize(("design", "options", "recommended"), [
    ("trial", ["CONSORT"], ["CONSORT"]),
    ("cohort", ["STROBE", "RECORD", "TARGET"], None),
    ("other", [], None),
])  # fmt: skip
def test_the_guidelines_offered_are_the_design_s(tmp_path: Path, design, options,
                                                 recommended) -> None:  # fmt: skip
    root = no_git(tmp_path / "paper")
    answered(root, {"schema": "manuscript-guard/setup/1", "study_type": design})
    question = next(q for q in asked(root).questions if q.id == "reporting_guideline")
    assert [o.value for o in question.options] == options
    assert question.recommended == recommended
    assert question.other  # a guideline outside the design's is taken too


def test_the_study_design_is_offered_whole_for_a_shortlist_of_three(tmp_path: Path) -> None:
    from manuscript_guard.gates.design import study_types

    question = next(q for q in asked(no_git(tmp_path / "p")).questions if q.id == "study_type")
    assert [o.value for o in question.options] == [*study_types(), "other"]
    assert question.shortlist == 3
    assert question.recommended is None


@pytest.mark.parametrize(("place", "value", "said"), [
    ("start", "nowhere.docx", "neither"),
    ("title", "A title with a \u0007 bell", "the title holds"),
    ("journal", "no-such-profile", "no profile of this project"),
    ("authors", [{**ADA, "orcid": "0000-0002-1825-0098"}], "check digit"),
    ("authors", [{**ADA, "corresponding": False}], "corresponding author"),
    ("authors", [{**ADA, "email": "ada at example"}], "not an address"),
    ("data", {"where": "project", "folder": "results"}, "toolkit's own folder"),
    ("data", {"where": "project", "folder": "../elsewhere"}, "not a folder inside"),
    ("language", "fr", "is not one of"),
    ("colour", "blue", "no question is answered at `colour`"),
])  # fmt: skip
def test_an_answer_that_cannot_be_taken_keeps_its_question_open_with_why(
    tmp_path: Path, place, value, said
) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {"schema": "manuscript-guard/setup/1", place: value})
    found = asked(root)
    problems = {q.id: q.problem for q in found.questions if q.problem}
    assert any(said in problem for problem in problems.values()), problems
    assert not found.ready


def test_a_role_names_an_author_answered(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {"schema": "manuscript-guard/setup/1", "authors": [ADA, CHARLES],
                    "statistician": "Nobody"})  # fmt: skip
    question = next(q for q in asked(root).questions if q.id == "statistician")
    assert [o.value for o in question.options] == ["Byron", "O'Neil", "later"]
    assert "names no author" in question.problem


def test_a_journal_s_profile_is_named_by_its_name_folded(tmp_path: Path) -> None:
    from manuscript_guard.setup.answers import journal_slug

    assert journal_slug("BMJ Open") == "bmj-open"
    assert journal_slug("Thérapie") == "therapie"
    assert journal_slug("The Lancet: Digital Health") == "the-lancet-digital-health"
    root = no_git(tmp_path / "paper")
    answered(root, {"schema": "manuscript-guard/setup/1", "journal": {"name": "臨床薬理"}})
    problem = next(q.problem for q in asked(root).questions if q.id == "journal")
    assert "no letter or digit" in problem
    answered(root, {"schema": "manuscript-guard/setup/1",
                    "journal": {"name": "臨床薬理", "slug": "rinsho-yakuri"}})  # fmt: skip
    assert "journal" not in [q.id for q in asked(root).questions]


def test_orcid_check_digit() -> None:
    assert orcid_ok("0000-0002-1825-0097")
    assert orcid_ok("0000-0002-7483-2489")
    assert not orcid_ok("0000-0002-1825-0098")


def test_every_question_is_a_place_the_answers_schema_takes() -> None:
    schema = load_schema("setup")["properties"]
    for place, _build in QUESTIONS:
        first, _, rest = place.partition(".")
        assert first in schema, place
        if rest:
            assert rest in schema[first]["properties"], place


def test_the_answers_schema_takes_what_paper_and_authors_take() -> None:
    setup, paper, authors = load_schema("setup"), load_schema("paper"), load_schema("authors")
    assert setup["properties"]["study_type"]["enum"] == paper["properties"]["study_type"]["enum"]
    credit = setup["properties"]["authors"]["items"]["properties"]["credit"]["items"]["enum"]
    assert credit == authors["$defs"]["author"]["properties"]["credit"]["items"]["enum"]


def test_answering_each_question_in_turn_reaches_ready(tmp_path: Path) -> None:
    """Every question answered by its first option, or its example, until none is open:
    no question is asked twice, and none is left waiting."""
    root = no_git(tmp_path / "paper")
    answers: dict = {"schema": "manuscript-guard/setup/1"}
    seen = []
    for _round in range(10):
        found = asked(root)
        if found.ready:
            break
        for question in found.questions:
            assert question.id not in seen, question.id
            seen.append(question.id)
            value = _an_answer(question)
            first, _, rest = question.id.partition(".")
            if rest:
                answers.setdefault(first, {})[rest] = value
            else:
                answers[first] = value
        answered(root, answers)
    assert asked(root).ready, asked(root).questions


def _an_answer(question):
    if question.id == "title":
        return "A working title"
    if question.id == "authors":
        return [ADA]
    if question.kind == "number":
        return 5
    if question.id == "journal":
        return {"name": "Journal of Examples"}
    if question.kind == "several":
        return [question.options[0].value] if question.options else []
    return question.options[0].value


# ---------------------------------------------------------------------------- apply


def test_apply_refuses_while_a_question_is_open_and_writes_nothing(tmp_path: Path,
                                                                  capsys) -> None:  # fmt: skip
    root = no_git(tmp_path / "paper")
    answered(root, {**ANSWERS, "language": "fr"})
    before = files(root)
    assert main(["setup", "apply", str(root)]) == 1
    assert files(root) == before
    assert "Still open: language" in capsys.readouterr().out


def test_apply_writes_exactly_the_answers(tmp_path: Path, capsys) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, ANSWERS)
    assert main(["setup", "apply", str(root)]) == 0
    paper = settings(root)
    assert {key: paper.get(key) for key in ("title", "english_variant", "study_type",
                                             "reporting_guideline", "target_journal",
                                             "registration", "stage")} == {
        "title": ANSWERS["title"], "english_variant": "en-GB", "study_type": "cohort",
        "reporting_guideline": ["STROBE", "RECORD"], "target_journal": "bmj-open",
        "registration": [{"id": "NCT01234567"}], "stage": "design",
    }  # fmt: skip
    authors = yaml.safe_load((root / "authors.yaml").read_text(encoding="utf-8"))
    assert authors["affiliations"] == [
        {"id": "a1", "text": ADA["affiliations"][0]},
        {"id": "a2", "text": CHARLES["affiliations"][1]},
    ]
    assert [(a["given"], a["family"], a["affiliations"], a["corresponding"])
            for a in authors["authors"]] == [
        ("Ada", "Byron", ["a1"], True), ("Zoë", "O'Neil", ["a1", "a2"], False)]  # fmt: skip
    assert authors["authors"][0]["orcid"] == ADA["orcid"]
    assert authors["roles"] == {"statistician": "O'Neil"}
    assert "# ai_use:" in (root / "authors.yaml").read_text(encoding="utf-8")
    assert (root / "profiles" / "journals" / "bmj-open.yaml").is_file()
    assert "data/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert yaml.safe_load((root / ANSWERS_FILE).read_text(encoding="utf-8"))["applied_on"]
    capsys.readouterr()
    assert main(["check", str(root)]) == 0  # nothing setup wrote fails at design


def test_the_dry_run_writes_nothing_and_says_what_apply_writes(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, ANSWERS)
    before = files(root)
    dry = apply_answers(root, dry_run=True)
    assert files(root) == before
    done = apply_answers(root)
    assert dry.ok and done.ok
    assert dry.written == done.written
    Draft202012Validator(load_schema("setup-applied")).validate(applied_dict(done, str(root)))
    Draft202012Validator(load_schema("setup-questions")).validate(asked_dict(asked(root)))


def test_apply_a_second_time_writes_nothing_more(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, ANSWERS)
    assert apply_answers(root, today="2026-11-27").ok
    before = files(root)
    again = apply_answers(root, today="2026-11-27")
    assert again.ok and again.written == () and again.kept == ()
    assert files(root) == before


def test_a_project_under_way_has_only_its_blanks_filled(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    assert main(["init", str(root), "--title", "Kept title"]) == 0
    assert main(["set", "study_type", "trial", "--path", str(root)]) == 0
    answered(root, {**ANSWERS, "start": "markdown", "language": "en-US"})
    done = apply_answers(root)
    assert done.ok
    paper = settings(root)
    assert paper["title"] == "Kept title"  # not the placeholder, so not replaced
    assert paper["study_type"] == "trial"
    assert paper["english_variant"] == "en-US"  # it was blank
    assert any(change.what == "study_type: trial" for change in done.kept)
    assert yaml.safe_load((root / "authors.yaml").read_text(encoding="utf-8"))["authors"][0][
        "family"] == "Byron"  # the placeholder is blank


def test_filled_authors_are_kept_and_not_asked(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, ANSWERS)
    assert apply_answers(root).ok
    text = (root / "authors.yaml").read_text(encoding="utf-8")
    left = {key: value for key, value in ANSWERS.items()
            if key not in ("authors", "declarations", "statistician", "ethics_lead")}
    answered(root, left)  # a conversation that never asked them: the file answers
    found = asked(root)
    assert "authors" in [known.id for known in found.known]
    assert {"authors", "declarations", "statistician"}.isdisjoint(q.id for q in found.questions)
    assert (root / "authors.yaml").read_text(encoding="utf-8") == text


def test_another_language_declares_no_english_and_says_what_holds(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {**ANSWERS, "language": "other"})
    done = apply_answers(root)
    assert "english_variant" not in settings(root)
    assert any("writing checks" in note for note in done.notes)


def test_a_private_repository_may_commit_the_stored_sources(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {**ANSWERS, "repository": {"visibility": "private", "sources_in_git": True,
                                              "github_actions": False}})  # fmt: skip
    assert apply_answers(root).ok
    assert settings(root)["literature"] == {"sources_in_git": True}
    assert "literature/sources/*" not in (root / ".gitignore").read_text(encoding="utf-8")


def test_data_held_apart_write_the_custodian_s_count_and_leave_the_vault_to_a_person(
    tmp_path: Path,
) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {**ANSWERS, "data": {"where": "vault", "minimum_cell_count": 5}})
    done = apply_answers(root)
    assert done.ok
    assert settings(root)["custodian"] == {"minimum_cell_count": 5}
    vault = [step for step in done.after if "vault init" in step.why]
    assert vault and vault[0].who == "author"
    assert ".gitignore" not in [change.file for change in done.written]


def test_a_latex_project_is_made_with_its_manuscript(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    answered(root, {**ANSWERS, "start": "latex"})
    assert apply_answers(root).ok
    assert (root / "manuscript" / "main.tex").is_file()
    assert not (root / "manuscript" / "main.md").exists()


def test_a_setting_paper_yaml_refuses_stops_everything(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    assert main(["init", str(root)]) == 0
    text = (root / "paper.yaml").read_text(encoding="utf-8")
    (root / "paper.yaml").write_text(text + "anchor: &a x\nalias: *a\n", encoding="utf-8")
    answered(root, ANSWERS)
    before = files(root)
    done = apply_answers(root)
    assert not done.ok and "anchor" in done.refused
    assert files(root) == before


def test_a_folder_inside_a_project_is_refused(tmp_path: Path, capsys) -> None:
    root = no_git(tmp_path / "paper")
    assert main(["init", str(root)]) == 0
    assert main(["setup", "questions", str(root / "manuscript")]) == 2
    assert "inside the project" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_and_the_workflow_are_made_when_asked(tmp_path: Path) -> None:
    root = tmp_path / "paper"
    root.mkdir()
    if read_folder(root).repository is not None:
        pytest.skip("the temporary folder is inside a git repository")
    answered(root, {**ANSWERS, "repository": {"git": True, "visibility": "public",
                                              "github_actions": True}})  # fmt: skip
    assert apply_answers(root).ok
    assert (root / ".git").exists()
    assert (root / ".github" / "workflows" / "manuscript-guard.yml").is_file()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_word_paper_is_brought_in_with_the_authors_as_given(tmp_path: Path) -> None:
    root = no_git(tmp_path / "paper")
    markdown = "---\ntitle: From Word\nauthor: Ada Byron\n---\n\n# Introduction\n\nText.\n"
    (root / "paper.md").write_text(markdown, encoding="utf-8")
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=root, check=True, timeout=120)
    (root / "paper.md").unlink()
    answered(root, {**ANSWERS, "start": "paper.docx", "title": ""})
    assert [q.id for q in asked(root).questions] == ["stage"]  # a paper written is asked it
    recommended = asked(root).questions[0].recommended
    answered(root, {**ANSWERS, "start": "paper.docx", "title": "", "stage": recommended})
    done = apply_answers(root)
    assert done.ok, done.refused
    assert settings(root)["title"] == "From Word"
    assert settings(root)["stage"] == "drafting"
    assert (root / "manuscript" / "main.md").is_file()
    authors = yaml.safe_load((root / "authors.yaml").read_text(encoding="utf-8"))
    assert [a["family"] for a in authors["authors"]] == ["Byron", "O'Neil"]


# ---------------------------------------------------------------------------- the machine


class _Ran:
    def __init__(self, out: str = "", code: int = 0, raises: Exception | None = None):
        self.stdout, self.returncode, self.raises = out, code, raises

    def __call__(self, argv, **kwargs):
        assert kwargs["timeout"] > 0  # R is never waited on without a limit
        if self.raises is not None:
            raise self.raises
        return self


@pytest.mark.parametrize(("ran", "found", "said"), [
    (_Ran("4 6.0 TRUE TRUE TRUE"), True, "R 4.6.0"),
    (_Ran("4 6.0 TRUE FALSE FALSE"), False, 'install.packages(c(\'digest\')); then '
     'remotes::install_github'),
    (_Ran(raises=subprocess.TimeoutExpired("Rscript", 60)), False, "did not answer"),
    (_Ran("", code=1), False, "did not say"),
])  # fmt: skip
def test_r_is_asked_for_its_packages_with_a_limit(ran, found, said) -> None:
    (tool,) = prerequisites("r", run=ran, which=lambda name: "Rscript", env={})
    assert tool.found is found
    assert said in tool.said


def test_no_rscript_is_said() -> None:
    (tool,) = prerequisites("r", which=lambda name: None, env={})
    assert not tool.found and "MANUSCRIPT_GUARD_RSCRIPT" in tool.said
    assert prerequisites("undecided") == ()
