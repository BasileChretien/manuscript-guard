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
- **Known limits are documented.** A gate whose limits are undocumented gets trusted beyond
  them, so DESIGN.md's "Known gaps" is corrected in the same commit as the code.
- **No absolute paths, no author-specific configuration**, and no assumption that Claude
  Code is present.

## Versions

The package and the plugin are one release with one number, written in four places, all of
which `tests/test_version.py` checks: `version` in `pyproject.toml`, `__version__` in
`src/manuscript_guard/__init__.py`, and `version` in `plugin/.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json`. A pull request leaves all four exactly as `main` has them.
The maintainer raises the number on `main` after merges, in a pull request that does nothing
else, so there is no number to ask for. It used to be the pull request's to write, and two
open pull requests that took the same number were merged by git without a conflict, the
second under a number already released. The number still has to move, on `main`: a change
released under the old one is invisible to `pip install --upgrade`, which decides on it, and
a plugin that moved alone would leave an installed tool behind the skills that call it.

## Running it

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

The R interoperability tests skip when R is absent, and the Zotero tests skip when Zotero
is not running. Neither is required to work on the rest.
