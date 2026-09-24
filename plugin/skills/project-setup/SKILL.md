---
name: project-setup
description: Start a manuscript-guard paper project and run its daily loop, from analysis plan to built .docx, and find which skill deals with a given finding. Use when starting a new paper, when adding manuscript-guard to an existing analysis repository, when paper.yaml or authors.yaml need filling in, or when unsure what to do next in a project that has a paper.yaml.
---

# Starting a paper project, and working in one

manuscript-guard makes the source of every number in a manuscript structural. Numbers from
the analysis are bindings into machine-written results, numbers from the literature are
bindings into a ledger backed by stored sources, and anything else has to be justified.
Change the analysis, rebuild, and the manuscript follows.

Everything that constitutes a guarantee is in the `manuscript-guard` command, which runs in
CI with no model involved. The skills help write and review, and never decide whether the
manuscript is clean. Keep that division when you work: an agent may draft a sentence, but
`check` decides.

The toolkit is alpha. Say so to anyone planning to rely on it for a submission.

## 1. What has to be installed

```bash
manuscript-guard --version
```

Python 3.10 or later is the only requirement. The rest is needed for one thing each, and
the tool says which when you reach it:

| | Needed for |
|---|---|
| pandoc | `build` and `submit`. Every gate runs without it |
| Zotero with Better BibTeX | live citation fields in the .docx, `sync-bib`, checking that citation keys are pinned |
| poppler (`pdftotext`) or pypdf | reading PDF sources and PDF figures |
| R with `jsonlite` and `digest` | only if the analysis is in R |

The plugin's hooks run `manuscript-guard-hook`, so the package must be on the `PATH` Claude
Code sees. Installed in a virtualenv the editor does not use, the hooks do nothing, and say
nothing.

## 2. Scaffold

```bash
manuscript-guard init my-paper --title "Working title"   # a new project
manuscript-guard init . --title "Working title"          # an existing analysis repository
```

It never overwrites an existing file, so the second form adds manuscript-guard to a
repository that already holds an analysis, with `paper.yaml` at its root. That also means
an existing `.gitattributes`, `.gitignore` or `README.md` is left as it was, without a word:
add `* text=auto eol=lf` and the binary lines to `.gitattributes`, and `build/` to
`.gitignore`, by hand. And `results/` belongs to manuscript-guard: every `.json` directly
in it is read as a results fragment and fails the schema if it is not one, and `verify`
empties the whole directory in its scratch copy. If the analysis already keeps its own
output there, either move that output, or set `paths: {results: <dir>}` in `paper.yaml`
and pass the same path to every emitter's `write()`, because the emitters default to
`results/` and do not read `paper.yaml`. It creates:

```
paper.yaml             stage, English variant, target journal, reporting guideline
authors.yaml           authors, affiliations, CRediT roles, funding, competing interests
design/plan.md         the analysis plan
analysis/              scripts that publish results through the emitter
results/               machine-written; never edited by hand
literature/            ledger.yaml, attested.yaml, references.bib, sources/
manuscript/main.md     prose with {{results.x}}, {{lit.y}}, [@citekey]
figures/  review/  build/
.gitattributes         * text=auto eol=lf
```

**Keep the `.gitattributes`.** Every digest is byte-exact, and a checkout that turns line
endings into CRLF makes clean results look hand-edited.

Then fill in, in this order:

1. **`authors.yaml`**: every author's `given` and `family` name and affiliations, taken
   from the author, never from what you know about anyone. The placeholder affiliation
   passes validation, so nothing will remind you to replace it. ORCID, CRediT roles, funding
   and competing interests are not enforced by the check. The submission pack reports a
   missing competing-interests statement per author, and CRediT and funding only when no
   author has any; a missing ORCID is left out without comment.
2. **`paper.yaml`**: the title, `english_variant` (`en-GB` or `en-US`), and the reporting
   guideline under the key `reporting_guideline` (singular, a list). Any key the schema does
   not know is a failure at every stage.
3. **`design/plan.md`**, before the analysis. The
   [analysis-plan](../analysis-plan/SKILL.md) skill covers it.

## 3. Stages

A checker that demands everything on the first day is switched off on the second, so each
finding declares when it starts to matter. Set `stage:` in `paper.yaml` and move it forward
as the work does:

| Stage | What you are doing |
|---|---|
| `design` | writing the analysis plan |
| `analysis` | writing and running the analysis |
| `drafting` | writing the manuscript against results that exist |
| `internal-review` | draft complete; panels, checklists and the journal's rules apply |
| `submission` | the version you send anywhere |

`init` sets `design`. With no `stage:` at all, the project is held to `drafting`. Every gate
runs at every stage; a finding not yet due is printed as `INFO` with `[not due until …]`,
not hidden. `manuscript-guard stages` lists which codes start to fail where. A failure not
listed there fails from the first day. Codes that only ever warn (the analysis plan, the
writing lint, `duplicate-quantity`) never fail, and the review and revision codes warn until
`submission`.

## 4. The loop

```bash
python analysis/01_model.py          # or Rscript: the analysis writes results/*.json
manuscript-guard check               # every gate; exit 1 on a failure, --json for machines
manuscript-guard explain manuscript/main.md   # how each number was classified
manuscript-guard bind                # each unbound number, and the ways to bind it
manuscript-guard verify              # re-run the analysis; do the numbers come out again?
manuscript-guard build               # the .docx, with live Zotero citations
manuscript-guard build --offline     # the same from references.bib, for CI and co-authors
```

Publishing values and binding them is the [results-binding](../results-binding/SKILL.md)
skill. `build` refuses while anything fails at the current stage. `--skip-checks` writes
`manuscript.UNCHECKED.docx` instead, which is for reading, not for sending.

`build` needs Zotero running for live fields; the first live build also downloads Better
BibTeX's Lua filter. `--offline` needs a `literature/references.bib`, which
`manuscript-guard sync-bib` writes from Zotero with just the cited keys. Commit it, so the
offline build works anywhere.

## 5. Which skill, when

Each finding names a code. The code says where to go:

| Codes | Skill |
|---|---|
| `no-analysis-plan`, `plan-section-*` | [analysis-plan](../analysis-plan/SKILL.md) |
| `unclassified-number`, `unresolved-binding`, `unquoted-result`, `hand-authored-table`, G1 and G8 codes | [results-binding](../results-binding/SKILL.md) |
| `ai-phrasing`, `ai-cadence`, `vague-attribution`, `model-artefact` | [manuscript-writing](../manuscript-writing/SKILL.md) |
| `methods-drift`, `methods-never-reconciled` | [methods-writer](../methods-writer/SKILL.md) |
| `literature-source-missing`, `quote-not-in-source`, `value-not-in-quote` | [literature-verify](../literature-verify/SKILL.md) |
| `figure-unreviewed`, `figure-review-stale` | [figure-review](../figure-review/SKILL.md) |
| `journal-profile-missing`, `over-journal-limit`, `missing-required-*` | [journal-profile](../journal-profile/SKILL.md) |
| `checklist-*` | [reporting-checklist](../reporting-checklist/SKILL.md) |
| `no-review`, `review-missing`, `review-stale`, `open-major-finding` | [review-panel](../review-panel/SKILL.md) |
| a co-author's edited .docx | [word-roundtrip](../word-roundtrip/SKILL.md) |
| `point-unanswered`, `claimed-change-*` | [reviewer-response](../reviewer-response/SKILL.md) |
| ready to send | [submission-pack](../submission-pack/SKILL.md) |
| a paper written without the toolkit | [paper-audit](../paper-audit/SKILL.md) |

## 6. What the hooks do in a project

With the plugin installed, four hooks act in any directory that has a `paper.yaml` above it:

- At the start of a session, one line of status: the stage, and how many findings fail and
  warn.
- Before a write, one to `results/`, `build/` or a generated checklist profile is refused.
  Change the analysis and re-run it; edit the recipe and re-transcribe.
- After a write: a saved manuscript file has its numbers classified and any unbound ones
  named. This is a quick check without section context, so `check` can still find more. A
  saved analysis file gets a reminder that the results are now stale.
- Before a shell command containing `--submission`, or one that copies, zips or pushes a
  submission or a `.docx`, the whole submission check runs and the command is refused if
  anything fails. That includes `manuscript-guard check --submission` itself. The refusal
  shows the first eight failures; `check --stage submission` runs the same check without
  the hook and lists them all.

## If you are a model doing this

Do not edit anything under `results/` or `build/` to make a check pass, even where the hook
cannot see it. Do not add a convention to `paper.yaml` to silence a number that should have
been bound. A pattern that exempts every number is allowed, and it is reported, and it
defeats the whole project.

When `check` fails, report the codes and what each one asks for. Do not summarise a failing
check as nearly clean.
