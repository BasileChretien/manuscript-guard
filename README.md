# manuscript-guard

[![CI](https://github.com/BasileChretien/manuscript-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/BasileChretien/manuscript-guard/actions/workflows/ci.yml)

> # ⚠️ ALPHA — DO NOT USE FOR REAL WORK YET
>
> **This project is published early so it can be read and criticised, not so it can be
> relied on.** No real paper has been written with it. Interfaces, file formats and gate
> behaviour will change without notice or migration. Do not point it at a manuscript you
> care about, and do not treat a passing `check` as evidence about a paper you are
> submitting.
>
> What it is safe to do today: read the code, read [DESIGN.md](DESIGN.md), run the worked
> example, and tell me where the reasoning is wrong — [CONTRIBUTING.md](CONTRIBUTING.md)
> says which kinds of wrongness are most useful.

Make every number in a scientific manuscript traceable to its source.

A number in a paper comes from one of three places: your results, the literature, or a
convention of scientific writing. `manuscript-guard` makes that structural rather than
aspirational. Numbers from your analysis are bindings into a machine-written results file,
numbers from the literature are bindings into a ledger backed by stored sources, and
anything else has to be justified. Change the analysis, rebuild, and the manuscript,
supplements and figures follow. A stale number is a build failure, not a discovery made by
a reviewer.

> **Status: alpha.** All thirteen gates, the document build, the literature tooling, the
> checklist transcriber, the review panels, the Word round trip and the submission pack work
> and are tested against a worked example — a test suite that gains a case for every defect found, and
> several rounds of adversarial review whose
> findings are recorded in [DESIGN.md](DESIGN.md) along with an honest list of what the
> toolkit cannot do. That is a long way from "trust it with your paper": the example is
> synthetic, no real manuscript has gone through it, and every round of review so far has
> found something the previous round's fix had opened up.

## How it works

Manuscript source is Markdown. Numbers appear as bindings:

```markdown
The database contained {{results.cohort.n_reports}} reports, of which
{{results.cohort.n_drug_reports}} named example-drug. The reporting odds ratio was
{{results.ror.point}} (95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}}).
```

Your analysis publishes those values, and only through an emitter that records where they
came from:

```python
from manuscript_guard.emit import Emitter

em = Emitter(__file__, inputs=["data/reports.csv"])
em.value("cohort.n_reports", 4000)
em.value("ror.point", 3.4211, digits=2)
em.write()
```

Then:

```bash
manuscript-guard check                 # every gate
manuscript-guard verify                # re-run the analysis; do the numbers still come out?
manuscript-guard build                 # the .docx, with live Zotero citations
manuscript-guard build --annotated     # the same, every number coloured by what backs it
manuscript-guard bind                  # every unbound number, and how to give it a source
manuscript-guard import edited.docx    # a co-author's Word edits, back into the source
manuscript-guard respond --open --from reviewed.docx   # a round, seeded from the comments
manuscript-guard respond               # the point-by-point response, and whether it is true
manuscript-guard check --submission    # submission standards
manuscript-guard submit                # the whole pack, ready to upload
```

`check` asks whether anything has been *disturbed*, and that is a question about digests —
which can be recomputed. `verify` asks a different question: it re-runs your analysis into a
scratch copy and compares the fragments value by value. A digest can be forged; a result
cannot be forged into existence. It is a separate command because it executes your code,
which a gate must never do, and because it takes as long as the analysis does.

`build` regenerates the .docx from Markdown every time. With Zotero open it writes **live
Zotero citation fields** — real `ADDIN ZOTERO_ITEM` fields that Word's plugin adopts, so
you can keep citing by hand in Word and refresh the bibliography as usual. Without Zotero,
`--offline` formats citations from a committed `references.bib`, which is what CI and a
co-author without your library get.

The document is a build artifact, never edited. Change the analysis, rebuild, and the
manuscript follows. Nothing is ever carried across by hand, so nothing can be forgotten.

## What the check actually guarantees

The check reads your **source**, where bindings are still visible, not the rendered output
where every number looks alike. That makes the rule simple and hard to slip past:

> In manuscript source, a bare numeric literal is a defect unless it is a recognised
> convention or a structural reference.

A results-derived number cannot be written as a literal at all, so nothing passes by
coincidence. The check also runs backwards: a value your analysis declares as quoted, which
no source file references, is a failure too. A registry that binds a handful of numbers and
reports "all clear" is worse than no registry.

Currently implemented:

| Gate | Checks |
|---|---|
| G1 | results are not older than the code or data that produced them |
| G2 | every number is classified, and every declared value is quoted |
| G3 | numbers in a figure's output *and in its source* trace back to results |
| G4 | word counts, required sections and required statements match the target journal |
| G5 | every reporting-checklist item is addressed, or excluded with a reason |
| G6 | model artefacts, AI phrasing, and unsupported appeals to authority |
| G7 | citations resolve and are pinned; every literature quote is in its source, and every value in its quote |
| G8 | one quantity is not emitted twice under two names |
| G9 | the analysis has not changed since the Methods were last read against it |
| G10 | every figure has a current review by someone who looked at it |
| G11 | a recorded panel has reviewed the manuscript, and its major findings are answered |
| G12 | there was an analysis plan, and its sections say something |
| G13 | every reviewer point is answered, and every claimed revision really happened |

`manuscript-guard check --submission` holds the manuscript to submission standards:
unanswered review findings become failures rather than warnings, so you can keep building
drafts to read while the version you send anywhere has to be clean.

Figures get three checks rather than one. The rendered output is read for numeric text; the
script is checked too, because a script that reads the results and *also* types one
annotation passes an output check today and goes stale tomorrow; and a model or a person
reads the picture, because no parser sees a truncated axis, an unexplained legend, or a
caption describing the figure the author meant to make. That last review is recorded in
`figures/<name>.review.yaml`, and the gate enforces that it exists, covered the required
ground, and applies to the figure as it now stands — not that it was any good.

## Design principles

**The guarantees are deterministic code.** No model output is trusted as evidence about the
text. `manuscript-guard check` runs in CI, offline, and gives the same answer every time.
A separate Claude Code plugin helps with drafting and review, but it never decides.

Two gates are a partial exception, and it is deliberate rather than accidental: G10 and G11
read a *recorded* review, and a review record classifies its own findings by severity. A
finding recorded as `fail` fails the run; the same observation recorded as `info` does not.
The record is the contract — a model may write one, and a person signs it. Nothing else in
the toolkit asks a model anything.

**Formatting is fixed where the number is computed.** `display` is set at emit time, so one
quantity cannot be rounded two ways in two sections. Cross-artefact consistency is a
property of the design rather than something checked afterwards. Note the limit: the emitter
fixes *where* a number is formatted, not that an explicitly supplied `display` matches the
value it is attached to.

**Numbers from the literature are verified, not trusted.** Each ledger entry stores the
value, the verbatim sentence that states it, and the source that sentence came from. The
quote must really be in the source and the value must really be in the quote — so the chain
from your manuscript to a published sentence is checked without anyone re-reading the
paper. Typographic differences are folded; paraphrases are not.

**Only a person can sign an attestation.** When you read something the toolkit cannot store
— a printed report, a withdrawn document — it goes in `literature/attested.yaml` with your
name on it. The gate refuses an `attested_by` naming a model, because that file exists to
record human accountability and is otherwise the easiest one for an agent to fill in on
your behalf.

**Journal rules and reporting checklists are retrieved, not built in.** Author guidelines
change without announcement, and writing STROBE's item text from memory would put
approximately-correct wording inside a toolkit whose whole argument is that approximately
correct is not good enough.

Checklists are therefore **transcribed from the guideline's own document by a recipe**:

```bash
manuscript-guard fetch STROBE        # downloads from the guideline's own site
manuscript-guard transcribe STROBE   # builds the profile locally
```

`fetch` downloads to your machine from the publisher's own address, printing the licence
first; nothing is redistributed by this project. The document is checksummed against the
recipe, so a revised checklist stops the build rather than producing a plausible wrong
transcription. Both commands write into `profiles/reporting/` in the project you are
standing in — pass `--root` to choose somewhere else. The recipes themselves ship inside the
package, and a recipe of the same name in your project overrides the shipped one. See [ATTRIBUTION.md](ATTRIBUTION.md) for each guideline's licence as read on
2026-08-03 — one of them is non-commercial, and several state no reuse licence at all.

Recipes ship for thirteen checklists: STROBE, RECORD, RECORD-PE, CONSORT, SPIRIT 2025,
PRISMA 2020 and its abstracts checklist, READUS-PV and its abstracts checklist, TRIPOD in
its three variants, and ARRIVE 2.0. You supply the official document; the profile is
generated locally and every item is verified to appear verbatim in it. Each profile records
how thoroughly it was verified, because that differs — a Word table allows every item's full
text to be checked, a column-laid-out PDF only each item's opening clause.

The transcribed text is not redistributed, so each guideline's licence stays the guideline's
business.

A guideline you have named but not retrieved fails loudly rather than passing quietly.

**The AI-writing lint measures rate, not presence.** It catches model artefacts outright
(`oaicite`, `[cite: 1]`, unfilled placeholders) and warns on well-catalogued phrasings, but
for ordinary words it counts. "Robust" describes a standard error and "significant" has a
technical meaning; six "crucial"s in four hundred words is the tell, not one. A lint that
flags robust standard errors gets switched off, and a lint that is switched off guards
nothing. It detects **habits, not authorship**, and says so.

**Exemptions are small, explicit and reviewable.** Conventions live in a narrow shipped
list pinned to specific values — `p < 0.05` is allowed, `p < 0.37` is not, because a p-value
you obtained is a result. Project additions require a written reason. Axis ticks are
declared per figure in a sidecar.

**The analysis language is yours.** The toolkit needs a results file, not a particular
language. Emitters exist for Python and R; anything that can write JSON can take part.

## Installation

Not on PyPI yet, so install from the repository:

```bash
git clone https://github.com/BasileChretien/manuscript-guard
pip install ./manuscript-guard
```

Or without cloning:

```bash
pip install git+https://github.com/BasileChretien/manuscript-guard
```

`pipx install ./manuscript-guard` works too, and is the better choice if you want the
command available everywhere without touching a project's environment.

Check it:

```bash
manuscript-guard --version
manuscript-guard stages
```

The package and the plugin carry one version number, and every change to either raises it, so
`manuscript-guard --version` names the release you have. To take a newer one:

```bash
pip install --upgrade git+https://github.com/BasileChretien/manuscript-guard
```

With pipx, `pipx upgrade` refuses a copy installed from git (it checks a package index, not
the repository), so reinstall instead:

```bash
pipx install --force git+https://github.com/BasileChretien/manuscript-guard
```

If pip says the requirement is already satisfied although the repository is ahead, the version
did not rise with that commit, and only a reinstall takes it:
`pip install --force-reinstall git+https://github.com/BasileChretien/manuscript-guard`.

The plugin's skills describe the commands of the release they came with, so keep the two
together (see [the plugin](#the-claude-code-plugin-optional) below). When the plugin is newer
than the installed command line tool, its session-start hook says so, once, with the upgrade
command, and blocks nothing. That warning comes from the tool itself, so a copy older than
0.2.260 cannot give it: upgrade such a copy once, by hand.

To work on the toolkit itself, install it editable with the test dependencies:

```bash
pip install -e ".[dev]"
pytest -q
```

### What else you need, and when

Only Python 3.10+ and two small libraries are required. Everything below is needed for one
particular thing, and the tool tells you which when you reach it.

| | Needed for | Without it |
|---|---|---|
| **pandoc** | `build`, `submit` | The gates all still run; you cannot produce a .docx |
| **Zotero + Better BibTeX** | live citation fields, `sync-bib` | Builds fall back to the committed `references.bib`; citation-key pinning goes unchecked |
| **poppler** (`pdftotext`) or **pypdf** | reading PDF sources and PDF figures | Those sources are reported as unverifiable rather than passed |
| **R** (+ `jsonlite`, `digest`) | emitting results from R | Only if your analysis is in R; the Python emitter needs nothing extra |
| **matplotlib** | the worked example's figure | Only for the example |

Nothing is fetched during installation. Reporting checklists are downloaded on request by
`manuscript-guard fetch`, never as an install side effect — see
[ATTRIBUTION.md](ATTRIBUTION.md) for why.

### The R emitter (only if your analysis is in R)

An analysis in R publishes its results through a small package that lives in this repository,
`r/manuscriptguard`. It is not on CRAN:

```r
install.packages("remotes")    # if you do not have it
remotes::install_github("BasileChretien/manuscript-guard", subdir = "r/manuscriptguard")
```

`install_github` also installs `jsonlite` and `digest`. From a clone,
`R CMD INSTALL r/manuscriptguard` does the same once those two are installed. Then, run from
the project root:

```r
library(manuscriptguard)
em <- mg_emitter("analysis/02_model.R", inputs = "data/cohort.csv")
em$value("model.n", 412L)
em$interval("model.or", 2.5, 1.8, 3.4, digits = 2)
em$write()
```

The fragment lands in `results/`, and `manuscript-guard check` reads it like one from Python.

### The Claude Code plugin (optional)

The pip package is the whole guarantee and needs nothing else. The plugin adds the parts
that need judgement — setting up a project, drafting, literature verification, figure
review, review panels, answering reviewers — plus hooks that catch mistakes at the moment
they are made.

This repository is its own plugin marketplace. Install once, and the skills and hooks are
there in every project you open:

```bash
claude plugin marketplace add BasileChretien/manuscript-guard
claude plugin install manuscript-guard@manuscript-guard
```

A local clone works as the source too: `claude plugin marketplace add /path/to/manuscript-guard`.
Restart Claude Code afterwards. Skills are namespaced, so they appear as
`/manuscript-guard:project-setup` and so on, and Claude also picks them up by description
without being asked.

The plugin is installed as a copy, so a new version of a skill reaches you only when you
ask for it:

```bash
claude plugin marketplace update manuscript-guard
claude plugin update manuscript-guard@manuscript-guard
```

To work on the skills themselves, load the directory for one session instead, and edits
apply on the next start: `claude --plugin-dir ./plugin`.

The hooks call `manuscript-guard-hook`, so the pip package has to be on the `PATH` that
Claude Code sees. Outside a manuscript-guard project they find no `paper.yaml` and do
nothing.

**Fourteen skills.** Start with `project-setup`; each of the others names the finding codes
that should send you to it.

| Skill | For |
|---|---|
| `project-setup` | starting a paper project, and the daily loop from analysis to .docx |
| `results-binding` | publishing values from the analysis, and turning a red number into a bound one |
| `analysis-plan` | writing the plan before the analysis, and recording deviations from it |
| `manuscript-writing` | prose that reads as written |
| `methods-writer` | Methods that describe the code that was actually run |
| `literature-verify` | a number from a paper, with its verbatim quote and stored source |
| `figure-review` | looking at a rendered figure and recording what was seen |
| `journal-profile` | choosing a journal with the author, and encoding its rules |
| `reporting-checklist` | STROBE, CONSORT, PRISMA and the rest, retrieved rather than remembered |
| `review-panel` | an internal review panel, recorded and answered |
| `word-roundtrip` | a co-author's Word edits, back into the source |
| `reviewer-response` | the point-by-point response to a journal, checked against the revision |
| `submission-pack` | everything the journal asks for, and the covering letter |
| `paper-audit` | a paper that was not written with this toolkit |

**Four hooks**, and what each is for:

| Hook | What it does |
|---|---|
| session start | One line: the stage, and how many findings fail and warn. And once, when the installed tool is older than the plugin, a notice with the upgrade command |
| before a write | Refuses edits to `results/`, `build/` and generated checklist profiles. These are written by something else, and editing one desynchronises it |
| after a write | For a manuscript file, classifies the numbers just saved and names any bound to nothing, while you are still in the paragraph. For an analysis file, says the results are now stale and the Methods may no longer describe the code |
| before a submission-shaped shell command | Runs the submission check and blocks if it fails |

The submission guard matches against the **whole command string** rather than a prefix rule,
because `cd example && manuscript-guard submit` and `FOO=1 manuscript-guard submit` both
defeat prefix matching. That is not hypothetical: it is how a submission slipped past the
guard in the project this one learned from.

A hook never breaks a session. Anything unexpected exits silently, because a guard that
crashes on a half-configured project gets removed, taking the guards that worked with it.

### Codex (optional)

Codex installs the same plugin from this repository, with the same fourteen skills and the
same four hooks. After the pip package:

```bash
codex plugin marketplace add BasileChretien/manuscript-guard
codex plugin add manuscript-guard@manuscript-guard
```

Neither command needs a login. Start a new Codex session afterwards. Both need the `codex`
command line tool; the desktop app on its own may not put it on your `PATH`.

Codex keeps a copy of the plugin, as Claude Code does. For the install above, from GitHub,
one command takes a new release, refreshing the marketplace and the installed plugin with
it:

```bash
codex plugin marketplace upgrade manuscript-guard
```

Upgrade the pip package at the same time. Codex may also refresh the copy without being
asked: its program carries an automatic upgrade of marketplaces, and when that runs was not
observed. Either way, when the plugin is the newer of the two, the session-start hook says
so once.

**Codex runs a hook only after you have trusted it.** By Codex's documentation, it warns at
the start of a session that hooks are waiting for review, and `/hooks` is where you read and
trust them: there are four, each a `manuscript-guard-hook` command. Until you do, nothing is
caught at the moment of the mistake. `check` and `build` run every gate either way.

| Hook | Under Codex |
|---|---|
| session start | As above |
| before a write | Codex edits files by applying a patch, which may write several files. A patch that adds or changes a file in `results/`, `build/` or a generated checklist profile, or moves a file into one, is refused whole, and the reason names those files. A patch that only deletes one is not refused |
| after a write | Each manuscript file in the patch that holds an unbound number, and each analysis file, gets its line |
| before a submission-shaped shell command | As above |

What Codex does not enforce. `check`, `build` and `submit` hold whatever the hooks do:

- By its documentation, a hook you have not trusted, or one whose definition changed since
  you trusted it, is skipped.
- The write guard sees a patch. A file written by a shell command is not seen, as under
  Claude Code.
- Codex's own documentation calls tool hooks "a useful guardrail, not a complete enforcement
  boundary", and says some tool paths can opt out of them.

How far this has been checked. Seen: the install, from GitHub by hand and from a checkout on
every pull request; the upgrade taking an installed copy from one release to the next; and
the hooks answering input shaped as Codex's source builds it. Not seen, because it needs a
login: a Codex session in which a skill is loaded, a hook is trusted or a hook fires. That
includes the session-start notice, which depends on Codex telling the hook where the plugin
is, as its documentation says it does.

### Gemini CLI, Mistral Vibe, Kimi Code CLI and other agent tools (optional)

By their own documentation, these tools read skills from a folder, `.agents/skills`, in your
home or in a project. After the pip package, one command copies the fourteen skills there:

```bash
manuscript-guard install-skills              # for you, in every project: ~/.agents/skills
manuscript-guard install-skills --project    # for one paper: .agents/skills in that project
```

Start a new session of the agent tool afterwards. `--dir <folder>` copies them anywhere
else, for a tool that reads another folder.

**It never writes over what it did not write.** The folder in your home is shared with every
other skill you have. A skill of yours with the same name as one of these is left as it is
and named, the others are copied, and the command exits 1; `--project` copies into the
paper's own folder, where nothing else is. A copied skill you have edited since is left too:
to take the new release of it, delete its folder and run the command again. What the command
may replace is recorded in a stamp beside the skills, `.manuscript-guard.json`. Leave it
there, and commit it with the skills if you commit them. If the command cannot read it, it
stops and touches nothing.

**To update,** upgrade the pip package and run the same command again. Until you do, `check`
and `build` say so: when a copy in either folder is from another release than the tool, one
line follows their own output, with the command to run.

**There are no hooks under these tools.** Nothing is caught at the moment of the mistake.
`check`, `build` and `submit` hold as they do everywhere, so an edited results file or an
unbound number is reported when one of them next runs.

| | Skills | `AGENTS.md` | Hooks |
|---|---|---|---|
| Claude Code | plugin | read where there is no `CLAUDE.md` | four |
| Codex | plugin | read | four, once you have trusted them |
| Gemini CLI | copy | read once a setting lists it | none |
| Mistral Vibe | copy | read in a folder you have trusted | none |
| Kimi Code CLI | copy | not confirmed | none |

For Gemini CLI the setting is `context.fileName`, in `.gemini/settings.json` of the project
or of your home:

```json
{ "context": { "fileName": ["AGENTS.md", "GEMINI.md"] } }
```

A Codex user without the `codex` command can use the copy in place of the plugin, and then
has no hooks. With both, Codex has every skill in two places it reads, the plugin and the
folder. What it then shows was not watched.

How far this has been checked: Gemini CLI 0.58.0 lists the fourteen skills from a project's
`.agents/skills`. That it reads the folder in your home, and that Mistral Vibe and Kimi Code
CLI read either, is from their own documentation and has not been watched. What each tool
does with `AGENTS.md` is from its documentation too, and for Kimi Code CLI that documentation
was not found to say. No skill has been used in a session of any of the three.

## Auditing a paper you already wrote

For a manuscript that was never built this way — no bindings, every number a literal —
there is one command:

```bash
manuscript-guard audit manuscript.docx supplement1.docx \
    --against results/ analysis_output.csv \
    --figures figures/
```

It reads the .docx with **tracked changes accepted** and **table cells kept apart** (Word
stores a row with no separator, so a naive read turns `39 | 20 | 26 | 16` into the single
number 39,202,616 and silently skips every table), drops the bibliography, classifies
conventions and cross-references, and reports every remaining number that appears nowhere
in your outputs.

**It also tells you how little that means.** The report ends with a measurement of the
backing set you supplied:

```
What a match is worth here:
  integers 1-100      100% of all possible values already match
  integers 1-1000     100%
  two-decimal           2%
  A match on a small integer means almost nothing here. Check those by hand.
  Point --against at the analysis outputs rather than the raw data if you can.
```

That measurement is the point. This audit can only ask whether a number appears *somewhere*
in the outputs, and in a previous project that question was measured as near-vacuous: 100%
of integers up to 100 already matched, and of fifteen deliberately corrupted headline
numbers it caught none. A clean audit report is not a clean paper, and the report says so
every time. Use `--strict` to exit non-zero on anything unmatched.

For a paper still being written, bind the numbers instead — then a stale one is impossible
rather than merely searched for.

## You do not have to satisfy every gate on day one

A checker that demands everything from the first day is a checker that gets switched off on
the second. So each finding declares the **stage at which it starts to matter**:

| Stage | What you are doing |
|---|---|
| `design` | writing the analysis plan |
| `analysis` | writing and running the analysis; the manuscript can wait |
| `drafting` | writing the manuscript against results that exist |
| `internal-review` | draft complete; panels, checklists and the journal's rules apply |
| `submission` | the version you send anywhere |

Set `stage:` in `paper.yaml`, or pass `--stage` for a single run:

```bash
manuscript-guard check --stage analysis
manuscript-guard stages                  # what binds where
```

**Every gate still runs at every stage.** Only the severity changes: a finding that is not
due yet is printed as `INFO` with `[not due until drafting]`, counted, and summarised at the
end. Nothing is skipped, because a check that quietly stopped looking would be worse than no
check. And a finding this policy does not know about fails at every stage — a new gate has
to opt in to being deferred. A gate that *crashes* reports `gate-errored`, which is in no
deferral list and so fails everywhere: a checker that could not check is not a pass.

The stage is declared in `paper.yaml`, not detected. Writing `stage: analysis` genuinely
does demote the drafting findings, so it is an opt-out for anyone who wants one — which is
the point, since the tool is for an author who wants it. What it is not is a hiding place:
every deferred finding is printed and counted.

## Getting started

```bash
manuscript-guard init my-paper
```

Among the files it writes is an `AGENTS.md`: the rules of the project on one short page, for
any agent working in it. Going by each tool's own documentation, Codex reads that file on its
own, Mistral Vibe does in a folder you have trusted, and Claude Code (2.1.277 or later) does
where there is no `CLAUDE.md` in the project or above it. Gemini CLI reads it once
`context.fileName` in its settings lists `AGENTS.md`. None of this has been watched in a
session. It is advice to the reader; the gates are what holds.

Then look at [`example/`](example/), a synthetic pharmacovigilance study that exercises
every gate, including a deliberately awkward case: a value the author read in a printed
agency report that no longer exists online, recorded as an attestation in
`literature/attested.yaml` rather than pretending to a stored source.

The example is in the repository, not in the installed package, so it needs a clone. Copy it
out and run the whole loop there. Its scripts import `manuscript_guard`, so use a Python that
has it installed (a `pipx` install gives you the commands only), and its figure is drawn with
matplotlib (`pip install matplotlib`):

```bash
cp -r manuscript-guard/example my-example && cd my-example
python analysis/00_simulate.py && python analysis/01_disproportionality.py && python figures/forest.py
manuscript-guard check
manuscript-guard build --offline     # writes build/manuscript.docx and build/supplementary.docx
```

A different matplotlib version draws a slightly different figure, and then `check` lists the
figure's recorded review as stale. That is `INFO` until the `internal-review` stage, as the
stage ladder above describes.

Useful when a finding surprises you:

```bash
manuscript-guard explain manuscript/main.md
```

It prints every numeric atom in the file and the rule that classified it.

## Licence

MIT.
