# Checking a paper in GitHub Actions

A paper kept in a GitHub repository can have `check` run on every push to its default branch
and on every pull request, with the documents built where it passes. A co-author then sees on
the pull request which findings their change opened, and the run keeps the report and the
.docx for anyone who can read the repository. Nothing runs that `check` and `build` do not run
on your own computer, no gate is softened for CI, and no secret is needed.

## Setting it up

In the project:

```bash
manuscript-guard init --github-actions
```

That writes `.github/workflows/manuscript-guard.yml` at the root of the git repository the
project is in, which is where GitHub reads a workflow, and nowhere else. A project that is a
folder of a larger repository is checked from there: the workflow's `path:` names its folder.
With no repository yet, the file goes into the project's own folder, which then has to be the
root of the repository you make. In a project set up already, `init --github-actions` writes
this file and nothing else, and it never writes over a file that is there. A new project can
be started with the flag too: `manuscript-guard init my-paper --github-actions`.

The workflow names the action at the version of manuscript-guard installed where you ran
`init`, and `init` prints it. A copy installed from the repository rather than from PyPI can
be ahead of the last release, for the hour or so between a number being raised and its release
being published; the workflow then names a tag that is not there yet, and fails to start until
it is. [The releases](https://github.com/BasileChretien/manuscript-guard/releases) list the
tags there are.

## The workflow

This is the file, with the version written `X.Y.Z`:

```yaml
# Written by `manuscript-guard init --github-actions`. It checks the manuscript at the stage
# paper.yaml declares and builds it, on each push to the default branch and each pull
# request, and keeps the report and the documents as the run's artefact. What it does and
# how to change it: https://github.com/BasileChretien/manuscript-guard/blob/main/docs/github-actions.md
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
        uses: BasileChretien/manuscript-guard@vX.Y.Z
        with:
          path: "."

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
      - uses: BasileChretien/manuscript-guard/badge@vX.Y.Z
        with:
          ok: ${{ needs.check.outputs.ok }}
          stage: ${{ needs.check.outputs.stage }}
```

Change what is yours: the branch, the runner, the time limit, and steps of your own before the
action. The action itself is `action.yml` at the root of manuscript-guard's repository, and
its inputs are:

| Input | Default | What it does |
|---|---|---|
| `path` | `.` | the project's folder, from the repository's root |
| `verify` | `false` | `true` runs `manuscript-guard verify` before check (below) |
| `requirements` | | a pip requirements file the analysis needs for `verify` |
| `python-version` | `3.12` | the Python manuscript-guard runs on |
| `pandoc-version` | the one manuscript-guard's own tests run with | the pandoc check and build run with |
| `tex-packages` | | more apt packages for a LaTeX manuscript, such as a journal's class |
| `artifact-name` | `manuscript-guard` | the name of the run's artefact |
| `retention-days` | `30` | how long GitHub keeps it |

## What the job does

1. It installs Python, and manuscript-guard from the action's own files, so the tool is the
   code at the version the workflow names.
2. It installs pandoc at the version manuscript-guard's own tests run with, poppler's
   `pdftotext`, which reads a stored source that is a PDF, and for a LaTeX manuscript the TeX
   Live packages its tests compile with. It finds the manuscript and the build folder where
   `paths:` in `paper.yaml` puts them.
3. With `verify: true`, it runs `manuscript-guard verify` (below). What verify prints stays in
   the job's log.
4. It runs `manuscript-guard check --json` at the stage `paper.yaml` declares. The job's
   summary gives the version and the stage, the failing findings and the warnings with their
   places (at most 200 of each, and fewer where they are long, since GitHub drops a summary
   larger than 1 MiB), and what no gate decides. Failures and warnings are also annotations, which a pull request shows
   beside the lines they are about; GitHub shows only some of them there. `check.json` has
   every finding.
5. Where check passed, it runs `manuscript-guard build --offline`. Where it failed, nothing is
   built: no artefact holds a document of a manuscript that fails at its stage. To read such
   a draft, build it on your own computer with `--skip-checks`.
6. It keeps the run's artefact: `check.json` and the documents, `manuscript.docx` and
   `supplementary.docx`, or `manuscript.pdf` and `supplementary.pdf`.
7. The job fails where verify failed, check failed or did not run, or the build failed or
   wrote no document.

## Rerunning the analysis

`check` knows a result is out of date from digests, in seconds. `verify` runs the analysis
again and compares every value, which catches a result that changed while its file did not,
and takes as long as the analysis does. It is off unless asked for, and it needs what the
analysis needs, set up in steps before the action:

```yaml
      - uses: r-lib/actions/setup-r@v2      # an analysis in R
      - uses: r-lib/actions/setup-renv@v2   # its renv.lock
      - id: guard
        uses: BasileChretien/manuscript-guard@vX.Y.Z
        with:
          path: "."
          verify: true
          requirements: requirements.txt     # an analysis in Python
```

It needs the inputs too. On restricted data they are not in the repository, so `verify`
cannot run there and the job fails on it: leave it off, and run `verify` where the data are
(`verify --receipt` at the site that holds them, [harvest](harvest.md)).

## What CI cannot reach, and what reads otherwise there

The gates give the answer they give anywhere, from what the checkout holds. Some things are
not in it:

- **Zotero**, so the build is offline: citations are formatted from the committed
  `literature/references.bib`, and live Zotero fields are never written.
- **The stored sources.** A new project keeps the copies in `literature/sources/` out of
  git, and `literature/sources.yaml`, which `sync-sources` writes and you commit, records
  them. A copy the record lists and git ignores is a note in CI, at every stage
  (`literature-source-not-here`, G7): its value is counted unverifiable, its quote is still
  held to the value, and only the quote's being in the copy goes unchecked. A passage, a
  quotation or an earlier output read from such a copy is noted the same way. Any other
  missing copy fails `literature-source-missing` from the `drafting` stage, and so does
  every missing copy where `paper.yaml` sets `literature: {sources_in_git: true}`.
- **The works store of reference currency**, `literature/currency/works/`, which stays out of
  git. A quote in a reading of currency is looked for there and, for the cited work, in its
  copy under `literature/sources/`; with neither, it is noted as unchecked
  (`currency-quote-unchecked`). And where the store has no record of a work an entry's
  readings name, the rules decide nothing for it, so a decision recorded `by: rules` is not
  checked against them in CI. Run `manuscript-guard references` where the store is kept.
- **Restricted inputs.** They reach CI as a Git LFS or git-annex pointer, whose digest G1
  compares; in a [vault](vault.md), whose record G1 reads; or covered by a site's receipt. An
  input that is only left out of git fails `input-missing` from the `analysis` stage.
- **Your Word styles.** The runner has no `reference.docx` of yours in pandoc's data folder,
  so the document is set in pandoc's default styles.

And some things read otherwise:

- **File times.** A checkout gives every file the time of the checkout. `analysis-newer`, a
  warning, compares them; so does `script-newer` for results written before the emitter
  recorded its script's digest, which running the script again records.
- **pandoc and pdftotext** are the runner's: where yours are other versions, the check of TeX
  that Word would drop and the reading of a PDF source can differ.

## The artefact, and restricted data

The artefact holds the report and the documents, and nothing else of the project: never
`results/`, an input or a stored source, nor what `verify` printed, since a script that fails
is quoted and may have printed its data (the job's log has it, for those who can read the
repository). Everything in the artefact is made from the checkout, and an
artefact is read by those with read access to the repository, so it reaches no one the
repository does not. A count below the custodian's minimum printed in a draft is in the
committed `results/` first, and G2 fails it from the `internal-review` stage.

## Upgrading

The action moves when the version in the workflow does. Dependabot can propose that as a pull
request, whose check then shows what the new version says of the paper. Releases come about
daily, so ask for it weekly, in `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```

## The badge

The badge says what the last run on the default branch found, in these words only:

- **manuscript-guard check | passes at stage drafting**, in blue;
- **manuscript-guard check | fails at stage drafting**, in red;
- **manuscript-guard check | did not run**, in grey.

The stage is the one the run held the manuscript to. A pass means that no finding due at that
stage is open, and is not evidence that the paper is right; at `design` it holds almost
nothing, which is why it is blue and not green. The badge is check's alone: a run can fail for
its build or its verify while the badge says check passes.

It is off until you set the repository variable `MANUSCRIPT_GUARD_BADGE` to `true` (Settings,
Secrets and variables, Actions, Variables: a variable, not a secret). Then, on each push to
the default branch, the workflow's `badge` job writes shields.io's description of the badge
to a branch of its own, `manuscript-guard-badge`, as its one commit. That job alone may write
to the repository; it checks nothing out and runs nothing of the project. Show it in the
README, with your repository's owner and name, and your default branch:

```markdown
[![manuscript-guard check](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/manuscript-guard-badge/badge.json)](https://github.com/OWNER/REPO/actions/workflows/manuscript-guard.yml?query=branch%3Amain)
```

Its limits:

- shields.io reads the branch from `raw.githubusercontent.com`, so the badge works for a
  public repository only;
- it shows the last finished run, so during a run it still shows the one before;
- a ruleset that forbids new branches stops it.

Before making a repository public for the badge, look at what it holds: `literature/sources/`
has the copies of the works the paper cites, paywalled ones among them. A new project's
`.gitignore` leaves them out, but `init` never rewrites an existing one, so a project made
before `init` wrote that line commits them, as does one whose `paper.yaml` sets
`literature: {sources_in_git: true}`. `git ls-files literature/sources` lists what is
committed. A public repository publishes it, in its history too.

## A weekly job for reference currency

Not yet. When `references --run` can search for newer evidence on its own, a second workflow
will run it weekly with a model provider's key as a repository secret, given to that one step,
and keep what it recorded as that run's artefact for you to read. It will never run on a pull
request, so a fork cannot reach the key, and the workflow above will need no change for it.
