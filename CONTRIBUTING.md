# Contributing

Thank you for looking. **This project is alpha and published to be criticised** — the most
useful contribution right now is telling me where the reasoning is wrong, not a pull
request against an interface that will change.

## What is most welcome

1. **A gate that is wrong.** Either direction: a number it flags that is not a defect, or a
   defect it waves through. The second is worth more. If you can write the failing case,
   `tests/test_corruption.py` is where it belongs.
2. **A claim in [DESIGN.md](DESIGN.md) that the code does not honour.** Several have been
   found this way, and each one was a real defect hiding behind flattering prose.
3. **A reporting guideline or journal whose requirements this cannot express.** RECORD 6.1
   is in because the toolkit forbade a table the guideline requires.

## The rules the code follows

- **A gate is deterministic and testable.** Anything that constitutes a guarantee lives in
  the pip package, with tests. An agent may help write a sentence; it never decides whether
  the manuscript is clean.
- **A gate without a test proving it catches the failure it claims to catch is not
  finished.** Add the failure to `tests/test_corruption.py`, not just a happy-path test.
- **A classifier rule names values, not shapes.** Every rule needs `accepts` *and* `rejects`
  cases in `tests/data/rule_cases.yaml`; the build fails without them. Read the header of
  that file first — it lists the eight times this rule was learned the hard way.
- **A rule that reads text is held over generated inputs.** `tests/test_properties.py` holds
  what every reading owes its input, on manuscripts drawn by `tests/generated.py`, and
  `tests/test_differential.py` reads the same inputs with the source your change is to be
  merged into and with your own. A difference fails; a pull request that means to change
  what a gate reports says so in `tests/data/differential_expected.yaml`.
- **Known limits are documented.** A gate whose limits are undocumented gets trusted beyond
  them, so DESIGN.md's "Known gaps" is corrected in the same commit as the code.
- **No absolute paths, no author-specific configuration**, and no assumption that Claude
  Code is present.

## Versions

The package and the plugin are one release with one number, written in four places, all of
which `tests/test_version.py` checks: `version` in `pyproject.toml`, `__version__` in
`src/manuscript_guard/__init__.py`, and `version` in `plugin/.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json`. A pull request leaves the version line in each of the four
exactly as `main` has it; the rest of those files is yours to change like any other. The
maintainer raises the number on `main` after merges that change `src/` or `plugin/`. That
bump is the one pull request that changes those four lines, and it changes nothing else, so
there is no number to ask for. A branch that already carries a bump puts `main`'s lines back.
It used to be the pull request's to write: two open branches then carried the same number,
which git merges without a conflict, the second under a number already released, and `main`
passed the number of a pull request that was waiting for its review. The number still has to
move, on `main`: a change released under the old one is invisible to `pip install --upgrade`,
which decides on it, and a plugin that moved alone would leave an installed tool behind the
skills that call it.

## Releases on PyPI

Every number on `main` goes to PyPI, with nobody's click. When a push to `main` raises the
version in `pyproject.toml` to one PyPI does not have, `.github/workflows/publish.yml`
builds the wheel and the source distribution, tags that commit `v` and the number
(`v0.2.431` for 0.2.431), makes the GitHub Release, and uploads them. So the maintainer's
bump is the release, and a pull request, which leaves the version line alone, never is one.

A release on PyPI is permanent: a version can be withdrawn, and never replaced or used
again. So a push that leaves the number alone releases nothing, nor does one that lowers
it, as a bump taken back does, and a number PyPI already has is not released twice
(`.github/scripts/release_decision.py`, with its cases in `tests/test_packaging.py`). The
workflow runs in this repository only, so a fork does not tag itself. It cannot be started
by hand, because a run by hand builds whatever `main` holds at that moment, and after a
later merge that is not the commit the number was raised on.

When a release does not go through:

- A run that failed is finished by re-running its failed jobs, on the Actions page. That
  builds the same commit, and makes the tag and the GitHub Release only where they are
  missing. So is a run GitHub cancelled, by re-running all its jobs: one run waits behind
  the one that is going, and a third push that touches `pyproject.toml` in those minutes
  cancels the one waiting.
- A run that says the commit it replaced cannot be read followed a forced push to `main`.
  It releases nothing, since nothing says that push raised the number. If it did, raise
  the number again in a commit of its own: that next number is the release, and the one
  passed over is never published.
- An upload that stopped after one of its two files is not finished by this workflow.
  PyPI then has the version, so a later run releases nothing, and a re-run of the failed
  job fails on the file already there. Raise the number again: the next release carries
  both files.

The upload carries no password and no token. PyPI trusts that one workflow file, in this
repository, in the `pypi` environment. That pairing is set on PyPI: as a pending publisher
of the maintainer's account until the first release, and in the project's publishing
settings after it. Renaming the file, or the environment, breaks the upload until PyPI is
told.

The description PyPI shows is built from the README, with each relative link and picture
pointed at the repository at the release's tag (`[tool.hatch.metadata.hooks.fancy-pypi-readme]`
in `pyproject.toml`), since a page on PyPI has nothing beside it. `tests/test_docs.py` builds
a wheel and reads its description for a relative target left in it, in the forms its
`relative_targets` names.

## Running it

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

The R interoperability tests skip when R is absent, and the Zotero tests skip when Zotero
is not running. Neither is required to work on the rest.
