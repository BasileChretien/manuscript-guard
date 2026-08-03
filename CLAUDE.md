# manuscript-guard

A toolkit for writing scientific manuscripts in which every number is traceable to its
source. Read [DESIGN.md](DESIGN.md) first — it holds the agreed architecture, the
verified environment findings and the build order.

This repository builds **tools for writing papers**. It is not itself a paper.

## Overview

Two layers:

- `src/manuscript_guard/` — pip package. The deterministic gates, the build pipeline and
  the Zotero client. Must run in CI with no LLM involved.
- `plugin/` — Claude Code plugin. Skills, agents and hooks that help draft, verify and
  review.

The separation is load-bearing: **an agent may help write a sentence but never decides
whether the manuscript is clean.** Anything that constitutes a guarantee belongs in the
pip package, with tests.

## Commands

```bash
pip install -e ".[dev]"      # from the repo root
pytest -q                    # 234 tests, ~55 s (R and Zotero tests skip if absent)
ruff check src tests
```

The example doubles as the test fixture. To see the whole loop:

```bash
cd example
python analysis/00_simulate.py && python analysis/01_disproportionality.py && python figures/forest.py
manuscript-guard check
manuscript-guard explain manuscript/main.md
manuscript-guard build --offline
```

CLI: `check` (all gates, exit 1 on failure, `--json` for machines), `build` (the .docx;
live Zotero fields by default, `--offline` for citeproc), `sync-bib` (rewrite
`references.bib` from Zotero), `explain` (how every number in a file was classified),
`render` (substitute bindings only), `init` (scaffold a project).

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
- pandoc is at `C:\Users\Basile\AppData\Local\Pandoc\pandoc.exe`, version 3.9.0.2.
- Multiple R versions are installed; use the newest unless a project pins one via renv.
