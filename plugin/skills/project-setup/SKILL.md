---
name: project-setup
description: Start a manuscript-guard paper project in conversation with its authors, each decision put to them as a question (in question boxes where the agent tool has them) and written by `manuscript-guard setup` as they answered, and learn its daily loop, from analysis plan to built .docx. Use when told to use manuscript-guard for a paper, when starting a new paper, when adding manuscript-guard to an existing analysis repository, or when paper.yaml or authors.yaml need filling in. Not for working out what to do next in a project already under way (use guide).
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
| pandoc | `build` and `submit`, and what `check` says of TeX in the text. Every other check runs without it |
| Zotero with Better BibTeX | live citation fields in the .docx, `sync-bib`, `sync-sources`, checking that citation keys are pinned |
| poppler (`pdftotext`) or pypdf | reading PDF sources and PDF figures |
| R with `jsonlite` and `digest` | only if the analysis is in R |

Some agent tools also run the toolkit's hooks (section 6). The hooks run
`manuscript-guard-hook`, so the package must be on the `PATH` the agent tool sees. Installed
in a virtualenv it does not use, the hooks cannot run: nothing is blocked and nothing is
guarded at the moment of the mistake, and `check` and `build` still run every gate. The
agent tool may then report a hook error that blocks nothing, which is the sign to look for.
Where the agent tool tells the hooks which release the skills are from, the session-start
hook says once when that release is newer or older than the installed tool, with the command
that brings the one behind up to date.

## 2. Start in conversation

When the author tells you to use manuscript-guard for a paper, or to start one, start here,
in the folder the paper is to live in, or in a project whose `paper.yaml` or `authors.yaml`
still has blanks. The authors make every decision; you ask, record and run. They never have to
type or read a manuscript-guard command: say what each step does in plain words, and give
the command only if they ask for it. Where the tool itself is missing, say what it is, that
it is the Python package `manuscript-guard` on PyPI, and ask before installing anything.

1. Run `manuscript-guard setup questions --json`. Say in a sentence what `known` holds, what
   the folder has decided already, then put the `questions` in their order, a few at a time.
2. Write each answer into `design/setup.yaml` with your file tools, never through a shell
   command, at the place its `id` names (`data.where` is `where:` under `data:`), exactly as
   the author gave it. The file begins `schema: manuscript-guard/setup/1`.
3. Run `setup questions --json` again. A question with a `problem` is asked again, its
   problem said in plain words; a question `waiting` comes in once what it waits `on` is
   answered. Go on until `ready` is true.
4. Run `manuscript-guard setup apply --dry-run --json` and read its `written` back as one
   summary in plain words, each change with its `why`, then its `kept` and `notes`. Ask for
   one yes to the whole of it. A change the author wants goes into the file, and back to 3.
5. On that yes, run `manuscript-guard setup apply --json`. Say what was written and why, and
   what `tools` this machine lacks and how to get it. Then take the `after` steps in order:
   hand each to its skill, and say a `who: author` step is theirs, and why.

**Putting a question.** Where your agent tool can put a question to the person as options to
pick from, a question box, put each in one: one decision per question, readable on its own,
its `question` and `why`, two to four `options`, each with its `label` and `effect`, the
`recommended` one first and marked "(Recommended)". Where none is recommended, give them in
their order and recommend none yourself. Several questions may go in one box. Where your
tool has no question boxes, number the options in your reply, mark the recommended one, and
wait for the answer. A question with more options than a box holds: the recommended one, the
next in order, and "another", which lists the rest.

- `study_type` has `shortlist: 3`: ask the author to describe the study in their words first,
  then offer the three options that fit that description best, and "None of these", which
  lists the rest. You choose only which three to show; the author chooses the design.
- `other` says what an answer outside the options is: a journal's name, another guideline.
- A `text`, `number` or `authors` question is asked in plain words in your reply, not in a
  box, and what you wrote is read back.
- `later` is an answer, written as `later`: the decision is put off, and `next` asks it when
  it is due.
- Never answer for the author from what you know of them or of anyone: a name, an
  affiliation, an ORCID iD, a grant, a journal, a design.

[references/conversation.md](references/conversation.md) has what each question needs.
[references/by-hand.md](references/by-hand.md) has the commands `setup` runs, for an author
who asks for them, and what `init` writes that no question asks about.

`init` makes the project:

```
paper.yaml             stage, English variant, target journal, reporting guideline
authors.yaml           authors, affiliations, CRediT roles, funding, competing interests
design/plan.md         the analysis plan; design/setup.yaml, the answers, beside it
analysis/              scripts that publish results through the emitter
results/               machine-written; never edited by hand
literature/            ledger.yaml, attested.yaml, references.bib, sources.yaml, sources/
manuscript/main.md     prose with {{results.x}}, {{lit.y}}, [@citekey]
                       (main.tex and mgvalues.sty under --latex, with \mg{results.x})
figures/  review/  build/
.gitattributes         * text=auto eol=lf, and *.svg binary among the files kept as bytes
AGENTS.md              the rules of the project, for any agent working in it
```

**Keep the `.gitattributes`.** Every digest is byte-exact, and a checkout that turns line
endings into CRLF makes clean results look hand-edited. An SVG figure is kept as bytes: svglite
on Windows writes CRLF, and normalised to LF the figure is no longer the one its render record
and its review hold. **`literature/sources/` stays out of git** unless the authors chose to
commit it in a private repository. **`results/` belongs to
manuscript-guard**: every `.json` directly in it is read as a results fragment.

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
skill. In a LaTeX manuscript, run `manuscript-guard values` after the analysis, which writes
`mgvalues.sty` from the results, and `explain manuscript/main.tex`; `build` compiles the PDF
with latexmk, which TeX Live and MiKTeX provide, and `--skip-checks` writes
`manuscript.UNCHECKED.pdf`. Each table and figure goes in a float with a `\caption`, which
LaTeX numbers it by. `build` refuses while anything fails at the current stage. For a Markdown manuscript,
`--skip-checks` writes `manuscript.UNCHECKED.docx` instead, which is for reading, not for
sending. A stale `.docx` (`document-stale`) never stops the Word build that rewrites it.

`build` needs Zotero running for live fields; the first live build also downloads Better
BibTeX's Lua filter. `--offline` needs a `literature/references.bib`, which
`manuscript-guard sync-bib` writes from Zotero with just the cited keys. Commit it, so the
offline build works anywhere. An offline build's citations are text, which Word's Zotero
plugin cannot refresh: the build says so and why a live one would not work now, and `check`
notes it (`citations-not-live`). Tell the author before sending them a document built
offline when they expect Zotero fields.

## 5. What to do next, and which skill

```bash
manuscript-guard next            # what to do now, with its skill and its command
manuscript-guard next --json     # the same, for an agent
```

`next` runs every gate and puts what to do in order, upstream first: what stops the check,
stale results, the plan, a choice that is due, a number with no source, the other failures,
then warnings and the next stage. Each action names the skill that deals with its findings
and the exact command. Working through the project with the author turn by turn is the
[guide](../guide/SKILL.md) skill. Most findings' hints in `check` name their skill too.

What arrives without a finding code, `next` does not route. These skills deal with it:

- which dataset could answer the question, and how it is reached:
  [data-sources](../data-sources/SKILL.md);
- a figure's look or palette: [figure-design](../figure-design/SKILL.md);
- an earlier abstract, preprint or article on the same data:
  [related-outputs](../related-outputs/SKILL.md);
- a question a co-author should check that no gate can:
  [co-author-checking](../co-author-checking/SKILL.md);
- a co-author's edited .docx: [word-roundtrip](../word-roundtrip/SKILL.md);
- a journal's decision letter and its reviewers' reports:
  [reviewer-response](../reviewer-response/SKILL.md);
- ready to send, or the code and results to deposit:
  [submission-pack](../submission-pack/SKILL.md);
- a paper written without the toolkit: [paper-audit](../paper-audit/SKILL.md).

## 6. What the hooks do in a project

Not every agent tool runs hooks, and one that does may ask you to approve them first. Where
they run, five hooks act in any directory that has a `paper.yaml` above it. Where they do
not, nothing below happens at the moment of the mistake. `check` still reports an edited or
stale results file and an unbound number afterwards, and `submit` still refuses a manuscript
that fails the submission check. Two things are then caught by nothing: a generated
checklist profile edited by hand, and a file edited in `build/`, which stays as edited until
the command that writes it runs again (`build` for the documents, `respond` for the letter).
Do not edit either. And a shell command that copies, zips or pushes a `.docx` is held to no
check, so run `manuscript-guard check --stage submission` yourself before a manuscript
leaves.

- At the start of a session, one line of status: the stage, how many findings fail and
  warn, and "Next:" with what `manuscript-guard next` puts first. Where a file of the
  project cannot be used (`paper.yaml`, `authors.yaml`, a results file or a ledger that does
  not parse or is not UTF-8), that line says which file and why in its place, and no gate
  has run until the file is put right.
- Before a write, one to `results/`, `build/` or a generated checklist profile is refused.
  Change the analysis and re-run it; edit the recipe and re-transcribe.
- After a write: a saved manuscript file has its numbers classified and any unbound ones
  named. This is a quick check without section context, so `check` can still find more. A
  saved analysis file gets a reminder that the results are now stale.
- Before a shell command containing `--submission`, or one that copies, zips or pushes a
  submission or a `.docx`, the whole submission check runs and the command is refused if
  anything fails, or if a file of the project cannot be used and the check cannot run. That
  includes `manuscript-guard check --submission` itself, `submit`, and a build asked for
  with `--stage submission`. The refusal shows the first eight
  failures; `manuscript-guard check --stage submission`, on a line of its own, runs the same
  check without the hook and lists them all.
- At the end of a turn that changed a file in `manuscript/`, `analysis/`, `results/`,
  `figures/` or `literature/`, or `paper.yaml` or `authors.yaml`, the line of the session's
  start again, with the counts as they now are. It is shown to the person and not to the
  agent, and blocks nothing.

## If you are a model doing this

Do not edit anything under `results/` or `build/` to make a check pass, even where no hook
stops you. Do not add a convention to `paper.yaml` to silence a number that should have
been bound. A pattern that exempts every number is allowed, and it is reported, and it
defeats the whole project.

When `check` fails, report the codes and what each one asks for. Do not summarise a failing
check as nearly clean.

After a `gate-errored` finding, offer `manuscript-guard report-issue <fingerprint>` with the fingerprint its hint names; after a sentence saying the tool itself failed, `manuscript-guard report-issue --last`.
For a gate that got something wrong, propose the smallest made-up text that shows it for `report-issue --about`, show it to the author, and never fill `--snippet` with the manuscript's own sentences unasked.

Where the data are held in a vault (`design/vault.yaml`, docs/vault.md), read them in the
analysis with `em.vault_input("<label>")`, which gives the synthetic copy in
`data/synthetic/`, and work on that copy only. Never read, list or name the vault's folder.
`vault run` and `vault release` are the person's, at a terminal: ask them to run them, and
read how a run went in `.manuscript-guard/vault/last-run.json`. `vault-result-unreleased`,
`vault-input-changed` and `vault-input-unregistered` are theirs to settle the same way.
