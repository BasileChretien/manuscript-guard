# manuscript-guard

A toolkit for writing scientific manuscripts in which every number is traceable to its
source. Read [DESIGN.md](DESIGN.md) first — it holds the agreed architecture, the
verified environment findings and the build order.

This repository builds **tools for writing papers**. It is not itself a paper.

## Overview

Two layers:

- `src/manuscript_guard/` — pip package. The deterministic gates, the build pipeline and
  the Zotero client. Must run in CI with no LLM involved.
- `plugin/` — Claude Code plugin. Skills and hooks that help set up, draft, verify and
  review.

The separation is load-bearing: **an agent may help write a sentence but never decides
whether the manuscript is clean.** Anything that constitutes a guarantee belongs in the
pip package, with tests.

## Commands

```bash
pip install -e ".[dev]"      # from the repo root
pytest -q                    # ~1500 tests, 18-28 min on Windows (R, Zotero, Claude Code, Codex, pandoc tests skip if absent)
ruff check src tests
claude plugin validate .     # the marketplace manifest; `plugin` validates the plugin itself
```

CI pins a pandoc version as `MANUSCRIPT_GUARD_REQUIRE_PANDOC` in `.github/workflows/ci.yml`,
installs it, and with that variable set `tests/conftest.py` refuses to start unless that
pandoc is on PATH. Set it to the same value locally to run the suite as CI does; unset, a
missing pandoc only skips the tests that need it.

The repository is its own plugin marketplace (`.claude-plugin/marketplace.json`, source
`./plugin`). The package and the plugin share one version, written in four places: `version`
in `pyproject.toml`, `__version__` in `src/manuscript_guard/__init__.py`, and `version` in both
`plugin/.claude-plugin/plugin.json` and the marketplace entry. **A pull request does not touch
those four.** The coordinating session raises them on `main` after each merge that changes
`src/` or `plugin/`, in a pull request of its own that changes nothing else (Basile,
2026-10-02). While every pull request bumped them, each merge put all the others in conflict
on the same four lines, and only one could be in CI at a time. A branch that still carries a
bump takes `main`'s side of the four files when it brings `main` in. Without a bump on `main`,
`claude plugin update` reports the old plugin as
current, and `pip install --upgrade` finds nothing newer for the package. `tests/test_version.py`
holds the four equal and `tests/test_plugin.py` the two manifests. When the installed tool is
older than the plugin, its session-start hook (`manuscript-guard-hook`) warns once and blocks
nothing.

The example doubles as the test fixture. To see the whole loop:

```bash
cd example
python analysis/00_simulate.py && python analysis/01_disproportionality.py && python figures/forest.py
manuscript-guard check
manuscript-guard explain manuscript/main.md
manuscript-guard build --offline    # writes manuscript.docx and supplementary.docx
```

Anything under `manuscript/supplementary/` is checked like the rest of the manuscript and
built as its own document, so it does not count against the journal's limits and can be
uploaded to the supplementary slot rather than pasted onto the end of the paper.

CLI: `check` (all gates, exit 1 on failure, `--json` for machines), `build` (the .docx;
live Zotero fields by default, `--offline` for citeproc), `sync-bib` (rewrite
`references.bib` from Zotero), `explain` (how every number in a file was classified),
`render` (substitute bindings only), `init` (scaffold a project),
`review --record <reviewer> --remit … --verdict …` (file the record G11 asks for, with the
digests filled in; `--record-figure <name> --by …` for G10). Neither can re-stamp an existing
record: a second reading is a second round.

The example's citekeys are fictional and live in its committed `references.bib`, so it
builds offline anywhere without touching anyone's Zotero.

Reporting checklists are generated, not committed:

```bash
manuscript-guard fetch STROBE --url <link> --save-url   # downloads; prints the licence
manuscript-guard transcribe                             # all recipes
```

Put the guideline documents in `profiles/reporting/sources/` (gitignored). Recipes are in
`profiles/reporting/recipes/`; generated profiles land beside them and are gitignored until
each licence is confirmed. Never hand-edit a generated profile — change the recipe and
re-run, so the profile stays a function of the published checklist.

## Conventions

- Public project, MIT. No absolute paths, no author-specific configuration, no assumption
  that Claude Code is present.
- Gates are deterministic and testable. A gate without a test that proves it catches the
  failure it claims to catch is not finished. Add the failure to
  `tests/test_corruption.py`, not just a happy-path test.
- Known limits go in DESIGN.md under "Known gaps". A gate whose limits are undocumented
  gets trusted beyond them.
- Prose in this repository, including documentation, must pass the project's own
  AI-writing lint once that exists.

## Environment facts that will bite

Verified 2026-08-03 on the author's machine.

- **The tool sandbox blocks localhost.** Anything talking to Zotero needs
  `dangerouslyDisableSandbox`.
- **Zotero's local API is disabled** (`403 Local API is not enabled`). Use **Better
  BibTeX's JSON-RPC** at `http://127.0.0.1:23119/better-bibtex/json-rpc`, which works and
  returns CSL-JSON with citation keys.
- **Zotero replies HTTP/1.0 close-delimited.** PowerShell and .NET reject this with
  "response ended prematurely"; Python's `urllib` is fine. Reach Zotero from Python only.
- Zotero must be **running** for the live-citation build; the build needs an offline mode
  for when it is not.
- pandoc on Windows installs per-user, at `%LOCALAPPDATA%\Pandoc\pandoc.exe`, and is often
  not on `PATH`. Verified against 3.9.0.2.
- **`jq` is not installed.** `gh ... --json x --jq '...'` works (gh has jq built in), and so
  does `--template`, but piping to a standalone `jq` fails silently inside a loop — a CI
  watcher written that way reports nothing and looks like a pending build.
- **`gh run view <id>` needs the id as a plain integer.** Reading it out of `--json
  databaseId` through anything that formats numbers turns it into `3.08e+10` and gets a 404;
  `--jq '.[0].databaseId'` returns it intact.
- Multiple R versions are installed; use the newest unless a project pins one via renv.
- **Word 365 is installed and scriptable over COM** (`New-Object -ComObject Word.Application`
  in PowerShell, `Visible = $false`, `Quit(0)` in a `finally`). That is how to learn what
  Word writes for an edit, rather than guessing: a move test that moved the whole `<w:p>`
  with its bookmark passed for months, and Word never makes that edit. Selection-based
  `Cut`/`Paste` borrows the clipboard; save and restore it.
- **`codex plugin` can be tried with no login and without touching the real installation**
  (verified 2026-10-02 with Codex 0.158):
  set `CODEX_HOME` to an empty folder, then `codex plugin marketplace add <checkout>` and
  `codex plugin add manuscript-guard@manuscript-guard`. `tests/test_plugin.py` does this where
  `codex` is on `PATH`, and CI's `codex-plugin` job always. A Codex binary may be on the
  machine without being on `PATH` (the desktop app keeps one under `.codex/plugins` in the
  user's home). Adding a marketplace from GitHub clones it under `CODEX_HOME`, and on Windows
  git fails with "Filename too long" when that folder is deep: use a short one.
