# manuscript-guard

A toolkit for writing scientific manuscripts in which every number is traceable to its
source. Read [DESIGN.md](DESIGN.md) first — it holds the agreed architecture, the
verified environment findings and the build order.

This repository builds **tools for writing papers**. It is not itself a paper.

## Overview

Two layers:

- `src/manuscript_guard/` — pip package. The deterministic gates, the build pipeline and
  the Zotero client. Must run in CI with no LLM involved. `panel/` is the one part that
  calls a model: it sends a review panel's remits to the providers an author lists and
  files the replies as review records. No gate imports it, and a test holds that.
- `plugin/` — Claude Code plugin. Skills and hooks that help set up, draft, verify and
  review.

The separation is load-bearing: **an agent may help write a sentence but never decides
whether the manuscript is clean.** Anything that constitutes a guarantee belongs in the
pip package, with tests.

## Commands

```bash
pip install -e ".[dev]"      # from the repo root
pytest -q                    # the whole suite (R, Zotero, Claude Code, Codex, pandoc tests skip if absent)
pytest -q -n auto -m "not timing" && pytest -q -m timing   # the same, as CI runs it
ruff check src tests
claude plugin validate .     # the marketplace manifest; `plugin` validates the plugin itself
```

CI pins a pandoc version as `MANUSCRIPT_GUARD_REQUIRE_PANDOC` in `.github/workflows/ci.yml`,
installs it, and with that variable set `tests/conftest.py` refuses to start unless that
pandoc is on PATH. Set it to the same value locally to run the suite as CI does; unset, a
missing pandoc only skips the tests that need it.

The generated tests (`tests/test_properties.py`, `tests/test_generated_sessions.py` and
`tests/test_differential.py`) draw the same inputs on every run. To look harder at a change,
draw more of them or from another seed, and name the commit to compare the working tree with:

```bash
MANUSCRIPT_GUARD_MORE_EXAMPLES=20 pytest -q tests/test_properties.py   # twenty times as many
MANUSCRIPT_GUARD_SEED=7 pytest -q tests/test_properties.py             # other inputs
MANUSCRIPT_GUARD_BASE=origin/main pytest -q -rs tests/test_differential.py
```

`tests/test_generated_sessions.py` draws twelve sessions from its seed `PINNED`, and holds
what the twelve contain. A change to `sessions()` in `tests/generated.py`, to `TAGS` or
`SAYS` in `tests/readings.py`, or to the Hypothesis pin draws twelve others, and that test
may then fail with nothing wrong in the import: its message says which numbers to try. Under the first two variables above,
the two tests of the pinned twelve are skipped.

Unset, the base is where the branch left `origin/main`. CI's `old-against-new` job compares
with the base-branch commit the pull request's merge was made on (the first parent of what
it checks out) and fails on any difference in what a reading of `tests/readings.py` reports.
A pull request that means to change one, or what a reading goes through, says so in
`tests/data/differential_expected.yaml` with the reason; the entry counts in that pull
request only. DESIGN.md, "Generated inputs belong to the suite", has the rest.

The repository is its own plugin marketplace (`.claude-plugin/marketplace.json`, source
`./plugin`). The package and the plugin share one version number, written in four places:
`version` in `pyproject.toml`, `__version__` in `src/manuscript_guard/__init__.py`, and
`version` in both `plugin/.claude-plugin/plugin.json` and the marketplace entry. **A pull
request does not touch the version: leave the version line in each of the four files exactly
as `main` has it.** The rest of each file is a pull request's to change like any other. The
coordinating session raises the number on `main` after merges that change `src/` or
`plugin/`, in a pull request that changes those four lines and nothing else. Do not ask it
for a number and do not pick one. A branch that already carries a bump puts `main`'s version
lines back, whether a merge of `main` conflicts on them or not; on a conflict, take `main`'s
side on all four lines. `tests/test_version.py` holds the four equal and
`tests/test_plugin.py` the two manifests. The session-start hook's warning that the tool and
the plugin differ blocks nothing.

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

The subcommands and what each does are in `docs/commands.md`, and their flags in
`manuscript-guard <command> --help`. What an agent must keep to:

- `review --run --yes` is for a script, never an agent's to add; `--dry-run` shows what would
  be sent and sends nothing.
- `review --record` and `--record-figure` never re-stamp an existing record: a second reading
  by the same reader is a further round.
- `search` proposes works a claim could cite and writes nothing; the author chooses.
- `set` writes one setting of `paper.yaml`; the hook asks before an agent moves the stage
  back, takes a guideline away or replaces the journal.

The README is the front page, and it and the pages its long tables moved to are held to the
tool by `tests/test_docs.py`: `docs/commands.md` lists exactly the subcommands (all but
`hook`) in the groups of `--help`, `docs/gates.md` exactly the gates, the README's summary of
each keeps to those groups and to the ones `check` ends with, every link in it and in
`docs/` resolves, and its pictures are what `python tools/readme_figures.py` draws and what
`check` prints. So a new command or gate needs its row in `docs/commands.md` or
`docs/gates.md`, a new skill its row in `docs/agent-tools.md` (`tests/test_plugin.py`), and a
change to what `check` says of a typed number needs the script's `CARD` updated and the
pictures drawn again. The long sections live under `docs/`.

The skills have one home, `plugin/skills`. The wheel takes them from there when it is built
and nothing under `src/` holds a copy, so edit them only there. The test suite sets
`MANUSCRIPT_GUARD_USER_SKILLS` to a folder that does not exist, so that `check` never reads
the copy of whoever is running it.

The example's citekeys are fictional and live in its committed `literature/references.bib`,
so it builds offline anywhere without touching anyone's Zotero.

Two data files are derived and never edited by hand; a wrong row is put right in the script
that writes it, with the authority for it. G14's spellings,
`src/manuscript_guard/data/spelling_variants.tsv`, come from VarCon through
`python tools/derive_spelling_variants.py path/to/varcon.txt`, which refuses any source but
the one whose SHA-256 it names; `varcon.txt` is not in the repository, and the file and
ATTRIBUTION.md keep VarCon's notices. The
palettes, `src/manuscript_guard/data/palettes.json`, their licences and the R package's
copies come from each collection's files at pinned commits through
`python tools/derive_palettes.py path/to/folder --fetch`. With `MANUSCRIPT_GUARD_VARCON` or
`MANUSCRIPT_GUARD_PALETTE_SOURCES` naming the sources, a test derives them again byte for byte.

Reporting checklists are generated, not committed: `manuscript-guard fetch STROBE --url
<link> --save-url` downloads a guideline's document and prints its licence, and
`manuscript-guard transcribe` runs all recipes. The documents go in
`profiles/reporting/sources/` (gitignored). Recipes ship in
`src/manuscript_guard/profiles/reporting/recipes/`, and a workspace's own
`profiles/reporting/recipes/` comes first; generated profiles land in `profiles/reporting/`
and are gitignored until each licence is confirmed.
Never hand-edit a generated profile — change the recipe and re-run, so the profile stays a
function of the published checklist.

## Conventions

- Public project, MIT. No absolute paths, no author-specific configuration, no assumption
  that Claude Code is present.
- Gates are deterministic and testable. A gate without a test that proves it catches the
  failure it claims to catch is not finished. Add the failure to
  `tests/test_corruption.py`, not just a happy-path test.
- A rule that reads text is held over generated inputs, and the campaign is the suite's. A
  change to such a rule adds what it needs to `tests/generated.py`, `tests/readings.py` and
  `tests/test_properties.py`; a generator in a scratch folder goes with the folder. A review
  reads the diff and runs these, and builds no campaign of its own: where a change needs one
  the suite lacks, that is the finding. A property is not finished until a broken rule fails
  it (`BROKEN` in `tests/test_properties.py`, `CHANGED` in `tests/test_differential.py`),
  and fails it under other draws than the pinned one: run the broken rule under a dozen
  values of `MANUSCRIPT_GUARD_SEED` before keeping the case. Where a property is about
  several kinds of edit or input, each example holds one of every kind. What a property
  draws first is what Hypothesis varies least, so a kind drawn first, one among several, is
  under some seeds never drawn, and a rule broken for that kind then passes.
- Tests never open a connection to a provider. The client takes its transport as an
  argument; `tests/test_review_transport.py` runs the real one against a server it
  starts on a loopback port.
- Known limits go in DESIGN.md under "Known gaps", above its "Closed since" line: an entry
  added at the end of the section reads as closed. A gate whose limits are undocumented gets
  trusted beyond them. A new entry ends in `Accepted.` (a limit that stays) or
  ``Pinned by `tests/test_file.py::test_name`.`` (the tests that hold it as written), and
  `tests/test_docs.py` holds that each test named is there.
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
- Zotero must be **running** for the live-citation build; `build --offline` works without it.
- pandoc on Windows installs per-user, at `%LOCALAPPDATA%\Pandoc\pandoc.exe`, and is often
  not on `PATH`. Verified against 3.9.0.2.
- **`jq` is not installed.** Use `gh ... --json x --jq '...'` (gh has jq built in) or
  `--template`. Piping to a standalone `jq` fails silently inside a loop, and a CI watcher
  written that way reports nothing and looks like a pending build.
- **`gh run view <id>` needs the id as a plain integer.** Anything that formats numbers turns
  `--json databaseId` into `3.08e+10` and gets a 404; `--jq '.[0].databaseId'` keeps it intact.
- **Word 365 is installed and scriptable over COM** (`New-Object -ComObject Word.Application`,
  `Visible = $false`, `Quit(0)` in a `finally`): learn from it what Word writes for an edit,
  rather than guessing. Selection-based `Cut`/`Paste` borrows the clipboard; save and restore it.
- **`codex plugin` can be tried with no login and without the real installation**: set
  `CODEX_HOME` to an empty folder with a short path (a deep one makes git fail), as
  `tests/test_plugin.py` does where `codex` is on `PATH` (CI's `codex-plugin` job always). The
  desktop app keeps its Codex binary off `PATH`, under `.codex/plugins` in the user's home.
