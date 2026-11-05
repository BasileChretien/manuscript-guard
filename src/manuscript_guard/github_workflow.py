"""The GitHub Actions workflow `init --github-actions` writes into a paper's repository.

It is a caller: the work is done by the composite action at the root of manuscript-guard's
repository (`action.yml`), which this file names at the version installed here, the only
pin `init` can know. What the author may want to change is in the caller, the triggers, the
runner and steps of their own before the action, and the rest is in the action, so a fix to
it reaches a paper when its pin moves. docs/github-actions.md says what the job does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Where GitHub reads a workflow: under the root of the repository, and nowhere else.
WORKFLOW = Path(".github/workflows/manuscript-guard.yml")

#: The page the workflow's header points to.
DOCS = "https://github.com/BasileChretien/manuscript-guard/blob/main/docs/github-actions.md"

#: The workflow, filled by `github_workflow`, which replaces its two placeholders. Not through
#: `format()`: each of GitHub's `${{ }}` would be read as a field. The header names no
#: version, since Dependabot moves the `uses:` lines and not a comment. The badge job is in
#: the file and off until the repository variable turns it on, so that its pin moves with
#: the check job's.
GITHUB_WORKFLOW = """\
# Written by `manuscript-guard init --github-actions`. It checks the manuscript at the stage
# paper.yaml declares and builds it, on each push to the default branch and each pull
# request, and keeps the report and the documents as the run's artefact. What it does and
# how to change it: @DOCS@
name: manuscript-guard

on:
  push:
    branches: [main]  # the repository's default branch, if it has another name
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: manuscript-guard-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  check:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    outputs:
      ok: ${{ steps.guard.outputs.ok }}
      stage: ${{ steps.guard.outputs.stage }}
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      # The steps an analysis needs for `verify: true` go here: the page above has them.
      - id: guard
        uses: BasileChretien/manuscript-guard@v@VERSION@
        with:
          path: @PATH@

  # The badge, "manuscript-guard check | passes at stage drafting". Off until the
  # repository variable MANUSCRIPT_GUARD_BADGE is set to true: read the page above first,
  # since it works for a public repository only.
  badge:
    needs: check
    if: >-
      always() && vars.MANUSCRIPT_GUARD_BADGE == 'true' && github.event_name == 'push'
      && github.ref_name == github.event.repository.default_branch
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      contents: write
    steps:
      - uses: BasileChretien/manuscript-guard/badge@v@VERSION@
        with:
          ok: ${{ needs.check.outputs.ok }}
          stage: ${{ needs.check.outputs.stage }}
"""


@dataclass(frozen=True)
class Workflow:
    """What `write_github_workflow` did: the file, whether it wrote it, the project's folder
    from the repository's root, and that root (None where no repository holds the project)."""

    path: Path
    written: bool
    folder: str
    repository: Path | None


def github_workflow(version: str, folder: str) -> str:
    """The workflow, pinned to `version`, checking the project at `folder` from the
    repository's root. The folder is written as a JSON string, which YAML reads as it is."""
    return (
        GITHUB_WORKFLOW.replace("@DOCS@", DOCS)
        .replace("@VERSION@", version)
        .replace("@PATH@", json.dumps(folder))
    )


def repository_root(start: Path) -> Path | None:
    """The nearest folder at or above `start` that holds a `.git`, a folder or the file a
    worktree or a submodule has; None where there is none."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def write_github_workflow(project: Path, version: str) -> Workflow:
    """Write the workflow at the root of the repository the project is in, or of the project
    where no repository holds it yet, and never over a file that is there."""
    project = Path(project).resolve()
    repository = repository_root(project)
    base = project if repository is None else repository
    folder = project.relative_to(base).as_posix()
    target = base / WORKFLOW
    if target.exists():
        return Workflow(target, False, folder, repository)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(github_workflow(version, folder), encoding="utf-8", newline="\n")
    return Workflow(target, True, folder, repository)
