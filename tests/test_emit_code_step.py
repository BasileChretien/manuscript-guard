"""A code step: Methods pointing at code an earlier run executed, which this run only names.

A study whose models were fitted by its own runners, on data that cannot be re-run casually,
pins each result file to the commit that produced it, and its emitting script only renders
those results again. A `step()` in that script digests the script, so no Methods paragraph
could point at the code that fitted the models: the co-author checking page said "no code is
linked" for every one. `code_step()` names that code, in another file of the project, and
holds it to the commit the results came from.

Each test makes its own git repository in a temporary folder; none reads a real project.
"""

from __future__ import annotations

import os
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from manuscript_guard.emit import Emitter

needs_git = pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")

CODE = '''\
"""The study's own runner, which fitted the models on the licensed data."""


def _weights(n):
    return [1 / n] * n


def fit_stacked(rows):
    """Fits the stacked model."""
    w = _weights(len(rows))
    return sum(r * x for r, x in zip(rows, w))


class Model:
    """A model."""

    def fit(self, rows):
        return fit_stacked(rows)
'''

ADAPTER = '''\
from pathlib import Path

from manuscript_guard.emit import Emitter

em = Emitter(__file__, root=Path(__file__).parent.parent)
em.code_step("model.stacked", "code/analysis.py", "fit_stacked", at="results-v1")
em.value("estimate", 0.79, digits=2)
em.write()
'''


def git(root: Path, *args: str) -> str:
    """git in `root`, whatever repository the environment names: a hook running the suite sets
    GIT_DIR to its own."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    done = subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.org", "-c",
         "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        cwd=root, capture_output=True, text=True, check=True, env=env,
    )  # fmt: skip
    return done.stdout.strip()


def study(root: Path, code: str = CODE, *, repository: bool = True) -> Path:
    """A project whose code was committed and tagged `results-v1`, as the study's runs were."""
    (root / "code").mkdir(parents=True, exist_ok=True)
    (root / "analysis").mkdir(exist_ok=True)
    (root / "manuscript").mkdir(exist_ok=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "M"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "code" / "analysis.py").write_text(code, encoding="utf-8")
    (root / "analysis" / "paper.py").write_text(ADAPTER, encoding="utf-8")
    if repository:
        git(root, "init", "-q")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "the run")
        git(root, "tag", "results-v1")
    return root


def run(root: Path, adapter: str = ADAPTER) -> dict:
    path = root / "analysis" / "paper.py"
    path.write_text(adapter, encoding="utf-8")
    runpy.run_path(str(path))
    fragment = yaml.safe_load((root / "results" / "paper.json").read_text(encoding="utf-8"))
    return fragment["steps"]


def edit(root: Path, was: str, now: str) -> None:
    path = root / "code" / "analysis.py"
    text = path.read_text(encoding="utf-8")
    assert was in text, was
    path.write_text(text.replace(was, now, 1), encoding="utf-8")


# ------------------------------------------------------------------------- what it records


@needs_git
def test_a_code_step_records_the_function_its_file_and_the_commit(tmp_path: Path) -> None:
    root = study(tmp_path)
    step = run(root)["model.stacked"]
    assert step["file"] == "code/analysis.py"
    assert step["function"] == "fit_stacked"
    assert step["at"] == "results-v1"
    assert step["commit"] == git(root, "rev-parse", "results-v1^{commit}")
    assert "unchecked" not in step
    assert step["lines"] == [8, 11], "the definition, from its def to its last line"
    assert step["follows"] == ["_weights"], "a function of the same file it calls is followed"
    assert len(step["digest"]) == 64


@needs_git
def test_a_method_and_a_class_are_named_through_their_class(tmp_path: Path) -> None:
    root = study(tmp_path)
    adapter = ADAPTER.replace('"fit_stacked"', '"Model.fit"')
    adapter = adapter.replace("em.value", 'em.code_step("model.class", "code/analysis.py", '
                              '"Model", at="results-v1")\nem.value')  # fmt: skip
    steps = run(root, adapter)
    assert steps["model.stacked"]["lines"] == [17, 18]
    assert steps["model.stacked"]["follows"] == ["_weights", "fit_stacked"]
    assert steps["model.class"]["lines"] == [14, 18]


@needs_git
@pytest.mark.parametrize(
    ("was", "now"),
    [
        ('    """Fits the stacked model."""\n', '    """Fits it."""\n'),
        ("    w = _weights(len(rows))\n",
         "    # the weights\n    w = _weights(\n        len(rows))\n"),
        ('    """A model."""\n', '    """A model of the data."""\n'),
    ],
    ids=["docstring", "comment and re-wrapped", "class docstring"],
)
def test_a_layout_or_comment_edit_since_the_commit_is_the_same_code(
    tmp_path: Path, was: str, now: str
) -> None:
    root = study(tmp_path)
    before = run(root)["model.stacked"]["digest"]
    edit(root, was, now)
    assert run(root)["model.stacked"]["digest"] == before


# ------------------------------------------------------------------------- what it refuses


@needs_git
@pytest.mark.parametrize(
    ("was", "now"),
    [
        ("return sum(r * x", "return max(r * x"),
        ("return [1 / n] * n", "return [2 / n] * n"),
    ],
    ids=["the function", "a function it calls"],
)
def test_code_that_is_not_the_code_at_the_commit_is_refused(
    tmp_path: Path, was: str, now: str
) -> None:
    root = study(tmp_path)
    edit(root, was, now)
    with pytest.raises(ValueError, match=r"is not the code it was at results-v1 \(commit"):
        run(root)


@needs_git
def test_a_function_added_since_the_commit_is_refused(tmp_path: Path) -> None:
    root = study(tmp_path)
    edit(root, "class Model:", "def later():\n    return 1\n\n\nclass Model:")
    adapter = ADAPTER.replace('"fit_stacked"', '"later"')
    with pytest.raises(ValueError, match="later is not defined in code/analysis.py at results-v1"):
        run(root, adapter)


@needs_git
def test_a_commit_the_repository_does_not_have_is_refused(tmp_path: Path) -> None:
    root = study(tmp_path)
    with pytest.raises(ValueError, match="names no commit or tag"):
        run(root, ADAPTER.replace("results-v1", "results-v9"))


@needs_git
def test_a_file_not_in_the_commit_is_refused(tmp_path: Path) -> None:
    root = study(tmp_path)
    (root / "code" / "later.py").write_text(CODE, encoding="utf-8")
    with pytest.raises(ValueError, match=r"code/later.py is not in results-v1"):
        run(root, ADAPTER.replace("code/analysis.py", "code/later.py"))


@needs_git
@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (('"fit_stacked"', '"fit_unstacked"'), "defines no fit_unstacked"),
        (('"fit_stacked"', '"_weights.inner"'), "defines no _weights.inner"),
        (('"fit_stacked"', '"fit-stacked"'), "is not a name of Python code"),
        (('"code/analysis.py"', '"../outside.py"'), "is outside the project"),
        (('"code/analysis.py"', '"code/missing.py"'), "cannot be read"),
        (('"code/analysis.py"', '"code/fit.R"'), "is not a Python file"),
        (('at="results-v1"', 'at="--all"'), "is no commit or tag"),
        (('at="results-v1"', 'at=""'), "is no commit or tag"),
        (('"model.stacked"', '"Model"'), "so that the Methods can bind it"),
    ],
    ids=["no such function", "inside a function", "not a name", "outside", "no file", "R",
         "an option", "empty", "step name"],
)
def test_a_code_step_that_names_no_code_of_the_project_is_refused(
    tmp_path: Path, change: tuple[str, str], refusal: str
) -> None:
    root = study(tmp_path)
    (root / "code" / "fit.R").write_text("fit <- function() 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match=refusal):
        run(root, ADAPTER.replace(*change))


@needs_git
def test_an_absolute_path_outside_the_project_is_refused(tmp_path: Path) -> None:
    root = study(tmp_path / "project")
    elsewhere = tmp_path / "elsewhere.py"
    elsewhere.write_text(CODE, encoding="utf-8")
    em = Emitter(root / "analysis" / "paper.py", root=root)
    with pytest.raises(ValueError, match="is outside the project"):
        em.code_step("model.stacked", elsewhere, "fit_stacked", at="results-v1")


@needs_git
def test_one_name_for_a_code_step_and_a_step_is_refused(tmp_path: Path) -> None:
    root = study(tmp_path)
    adapter = ADAPTER.replace("em.value", 'with em.step("model.stacked"):\n    x = 1\nem.value')
    with pytest.raises(ValueError, match="marks two different"):
        run(root, adapter)


@needs_git
def test_git_that_fails_in_a_repository_refuses_and_does_not_pass_as_no_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 1 of #564: any failure of git was read as "no repository", so code edited since
    `at` was recorded unchecked and passed. A broken configuration is git failing in a
    repository, and the step must be refused with what git said."""
    from manuscript_guard.emit import code_at, definition_code

    root = study(tmp_path / "project")
    edit(root, "return sum(r * x", "return max(r * x")
    broken = tmp_path / "broken.gitconfig"
    broken.write_text("[core\n\tthis is not a config\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(broken))
    file = root / "code" / "analysis.py"
    now = definition_code(file.read_text(encoding="utf-8"), "fit_stacked")
    with pytest.raises(ValueError, match="git could not be asked") as refused:
        code_at(file, "code/analysis.py", "fit_stacked", "results-v1", now)
    assert "config" in str(refused.value), "git's own message is carried"


def test_git_absent_from_path_is_recorded_unchecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard import emit

    root = study(tmp_path, repository=False)
    monkeypatch.setattr(emit.shutil, "which", lambda name: None)
    file = root / "code" / "analysis.py"
    now = emit.definition_code(file.read_text(encoding="utf-8"), "fit_stacked")
    commit, why = emit.code_at(file, "code/analysis.py", "fit_stacked", "results-v1", now)
    assert commit is None and why.startswith("git is not installed here")


# ------------------------------------------------------------------- without a repository


def test_without_a_repository_the_file_is_read_and_the_commit_said_unchecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As in the copy `manuscript-guard verify` runs, which has no .git: the step is recorded
    from the file as it is, and says the commit was not held to it, rather than failing."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    root = study(tmp_path, repository=False)
    step = run(root)["model.stacked"]
    assert "commit" not in step
    assert "no git repository holds code/analysis.py here" in step["unchecked"]
    assert step["lines"] == [8, 11]


@needs_git
def test_verify_re_runs_an_adapter_with_a_code_step_and_passes(tmp_path: Path) -> None:
    from manuscript_guard.contracts import load_project
    from manuscript_guard.verify import to_report, verify

    root = study(tmp_path)
    run(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the results")
    result = verify(load_project(root)[0])
    assert result.ok, to_report(result).render(root)
    assert any("estimate" in c.agreed for c in result.comparisons)
