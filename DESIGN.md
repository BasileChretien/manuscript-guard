# manuscript-guard — design

Status: design agreed 2026-08-03. **All eight phases built and tested.** 564 tests pass,
including the corruption harness described below and the regression tests from two
adversarial rounds. What remains is listed under Known gaps.

That list is load-bearing and has to be kept true. It drifted once — it went on claiming
five guideline licences were unconfirmed after they had been read, and went on describing
two defects that had been fixed — which is the same failure the toolkit exists to catch one
level down. Correct it in the same commit as the code, or it becomes a rumour.

## What this is

A toolkit for writing scientific manuscripts in which **every number is traceable to a
source**. It is not a paper. It is the machinery Basile Chrétien will use for subsequent
papers, released publicly under MIT so other scientists can use it.

It ships in two layers:

- a **pip package** (`manuscript-guard`) holding the deterministic gates, the build
  pipeline and the Zotero client. Runs anywhere, including CI, with no LLM involved.
- a **Claude Code plugin** holding the skills, agents and hooks that help draft, verify
  and review.

The split is deliberate and load-bearing. The guarantees belong to the deterministic
layer; an agent may help you write a sentence but never decides whether the manuscript is
clean. A user who does not use Claude Code still gets the guarantee.

### Non-goals

- Writing any particular paper.
- Replacing Zotero, pandoc or the analysis language.
- Requiring R. The toolkit is language-agnostic about the analysis and only requires the
  results contract; R and Python helpers exist for convenience.

## The core invariant

Every number in a deliverable resolves to exactly one of four classes:

| Class | Meaning | Example |
|---|---|---|
| `results` | a key in the machine-written results file | the cohort size |
| `literature` | a key in the literature ledger, backed by a stored source | a prevalence quoted from a published cohort |
| `convention` | a writing or statistical convention on a reviewed allowlist | `p < 0.05`, `95% CI` |
| `structural` | not a claim at all | `Table 2`, a publication year, a dose inside a drug name |

The check runs in **both directions**:

1. no numeric token in any deliverable may be unclassified;
2. no display value produced by the analysis may lack a bound claim, or be explicitly
   marked as not quoted.

Direction 1 alone lets a stale number hide somewhere nothing looks. Direction 2 alone
produces the failure recorded in the predecessor project, where a registry bound 28 of 236
values and still reported "all clear". Both together are what makes "no stale number" a
property of the build rather than a hope.

### Why the check runs on the source, not the output

The classifier reads the manuscript **source**, where bindings are still visible as
`{{results.x}}` placeholders, rather than the rendered output where every number looks
alike. That turns the check into something almost trivially strong:

> In manuscript source, a bare numeric literal is a defect unless it is a recognised
> convention or structural reference.

There is no matching of numbers against a backing set, and therefore none of the
coincidental-match weakness that made the predecessor's checker near-vacuous — it measured
that 100% of integers up to 100 were already "backed" by something, somewhere. Here a
results-derived number cannot be written as a literal at all: it is either a placeholder or
a build failure.

Two rules support it. Results are **never hand-written** — one machine-generated file
stamped with script, git SHA, input hashes and timestamp. And the build **refuses to run
when results are older than any analysis script or input file**, which is what makes "the
latest results are always used" mechanical rather than a habit.

## Empirical findings (verified 2026-08-03 on the author's machine)

These were tested, not assumed, and they determine the architecture.

- **pandoc + `zotero.lua` produces a .docx with live Zotero citations.** Real
  `ADDIN ZOTERO_ITEM CSL_CITATION` field codes, built by querying the running Zotero
  through Better BibTeX's JSON-RPC. Confirmed in Word: Zotero adopts the citations after
  Document Preferences, and the file is not reported as corrupt.
  **Consequence: Markdown is the permanent source of truth and the .docx is a disposable
  build artifact.** No surgical patching, no md/docx drift.
- `zotero.lua` emits no `ZOTERO_PREF` properties and no `ZOTERO_BIBL` field for .docx (it
  does for .odt), so a Word build had live citations, no reference list, and a style dialog on
  the first Refresh. `build/zotero_word.lua`, run after it on a live build, now adds both: the
  bibliography field where the manuscript writes a `refs` div (or at the end), and the
  preferences for the target journal's `references.csl`. Verified in Word 16 with Zotero
  9.0.6 on a 57-reference manuscript: Refresh formatted every citation in the preset style
  without a dialog, filled the bibliography, and Add/Edit Citation worked on the document.
  (Narrative `@key` citations also produced no field at the time of the first note; that
  was fixed with `author-in-text: true` — see "The build" below.)
- **Zotero's local API (`/api/`) is disabled** on this machine — returns
  `403 Local API is not enabled`. Not needed: **Better BibTeX's JSON-RPC works** and
  returns CSL-JSON including citation keys.
- **Zotero replies HTTP/1.0 with a close-delimited body.** .NET's HTTP client rejects this
  (`response ended prematurely`); Python's `urllib` handles it. All Zotero access must go
  through Python, never PowerShell.
- **The agent tool sandbox blocks localhost.** Any step touching Zotero needs the sandbox
  disabled, which has consequences for how hooks are written and permissioned.
- **Never ask Better BibTeX for the whole library.** `item.search("")` serialises every item
  as CSL: 51 s for 4,688 items (Better BibTeX 9.0.64), against G7's 20 s budget, so G7 passed
  or failed on how busy Zotero was. G7 now asks `item.pandoc_filter` about the cited keys
  (0.2 s; an unresolvable key comes back with the number of items carrying it, 0 or a
  duplicate count) and finds pinned items with one condition search,
  `item.search([["extra", "contains", "Citation Key:"]])` (0.7 s).
- **A pinned key comes back as `citation-key: xyz`**, in the CSL `note`, although it is typed
  in Extra as `Citation Key: xyz`. `item.search` keeps that line; `item.pandoc_filter` and
  `item.export` strip it, so they cannot tell pinned from unpinned.
- Environment: Zotero 9.0.6, Better BibTeX installed, `Zotero.dotm` in Word's STARTUP,
  pandoc 3.9.0.2, Word 16, R 4.3.3–4.6.0, Python 3.12.3.

## Structure

### The toolkit repository

```
manuscript-guard/
  src/manuscript_guard/
    contracts/     # schemas for results, ledger, authors, paper
    gates/         # one module per gate; deterministic, no LLM
                   #   includes journal.py and reporting.py: the guideline checkers
    build/         # md -> docx/pdf, zotero.lua, CSL, tables, figures
    zotero/        # BBT JSON-RPC client, citation-key pinning checks
    literature/    # stored sources, quote and value verification
    reporting/     # recipe-driven checklist transcription
    text/          # masking, tokenising, placeholders, docx and code readers
    data/          # the shipped convention, structural and term rules
    profiles/      # shipped, read-only: checklist recipes, journal profiles
    paths.py       # what is shipped vs what a project writes; see the note below
  r/manuscriptguard/   # mg_emitter() -> results fragment with provenance
  .claude-plugin/   # marketplace.json: the repository is its own plugin marketplace
  plugin/
    skills/  hooks/
  profiles/        # the *workspace*, not shipped data: downloaded guideline documents
    reporting/     #   and the profiles transcribed from them. Gitignored.
  example/         # synthetic pharmacovigilance study: demo and test fixture
  tests/
```

The two `profiles/` directories are not a duplication. Shipped and read-only data travels
inside the package so a wheel carries it; documents a user downloads and profiles built from
them are written into the project being worked on, never into `site-packages`. Keeping both
in one root-level directory is what made `manuscript-guard fetch` fail on every installed
copy — see the note under "What an adversarial review found".

### What it scaffolds into a paper project

```
<paper>/
  paper.yaml            # target journal, English variant, reporting guideline
  authors.yaml          # author block, CRediT roles, funding, competing interests
  analysis/             # R or Python; its only output of record is results.json
  results/results.json  # machine-written, never hand-edited, provenance-stamped
  literature/
    sources/            # PDFs and abstracts, filed by citation key
    ledger.yaml         # verified extracted values, each keyed and quoted
  manuscript/*.md       # prose with {{results.x}} / {{lit.y}} and [@citekey]
  manuscript/supplementary/*.md   # the same, built as its own document
  figures/              # scripts that may read results.json and nothing else
  build/                # docx/pdf artifacts, gitignored
```

`manuscript/supplementary/` is read by every gate that reads prose — a fabricated number in a
supplementary table is still fabricated, and a supplement nobody checks is the obvious place
to put one — and excluded from the two places that mean the main text specifically: the
journal's word and display-item limits, and the count the title page declares to the editor.
It builds as `supplementary.docx` and reaches the pack as its own file. A directory rather
than a declaration, matching how figures and results already work, and because a heading can
be renamed without anyone noticing what left the submission.

A document of its own also comes back from a co-author on its own. `import` compared every
returned document with a fresh build of the paper, so an edited `supplementary.docx` reported
every paragraph of the paper as deleted in Word and applied none of its own edits. The source
stamp cannot tell the two documents apart: both are built from the same sources and carry
the same one. The paragraph identifiers can, because each names its source file. A document
whose identifiers all come from `manuscript/supplementary/` is compared with a fresh build of
the supplement, and one whose identifiers all come from the paper with a build of the paper.
One carrying both is refused: neither build accounts for it. Word drops the identifier of a
single paragraph it pastes, so only two or more paragraphs pasted across bring one along. A
document carrying none is refused too when the project has a supplement, since it could be
either. Whether there is a supplement is read from the source files: a supplement of
headings and tables carries no identifier, and read from the identifiers it was taken for no
supplement, so its document was compared with the paper.

`authors.yaml` is structured rather than prose because journals want more than name and
affiliation: CRediT roles per author, corresponding-author contact block, equal-
contribution groups, ORCID, funding and competing interests. One validated file fills the
title page, the declarations section and the submission form, and the submission gate
refuses to build while a required field is empty. A human-readable Markdown version is
rendered from it.

## The gates

All deterministic, all runnable in CI without Claude.

| | Gate | Fails when |
|---|---|---|
| G1 | Results freshness | `results.json` older than any analysis script or input file |
| G2 | Number classification | a numeric token is unclassified, or a display value has no bound claim |
| G3 | Figures | a number in a figure's output or in its source is not traceable to results |
| G4 | Journal profile | word counts, structure, reference style, required statements |
| G5 | Reporting checklist | a checklist item is unaddressed |
| G6 | AI-writing lint | banned constructions and cadence tells |
| G7 | Citation integrity | unpinned or unresolvable citation key; literature claim with no stored source |
| G8 | Cross-artifact consistency | a quantity differs between abstract, results, table and figure |
| G9 | Methods drift | analysis code changed since the Methods text was last reconciled |
| G10 | Figure review | a figure has no current review, or its review raised concerns |
| G11 | Panel review | no review round, a stale review, a file nobody read, or an unanswered major finding |
| G12 | Methods appropriateness | the analysis plan does not answer the question asked |
| G13 | Response to reviewers | a point unanswered, or a claimed revision that did not happen |

Plus one code that belongs to no gate: `gate-errored`, raised when a gate itself throws. It
is in no stage's deferral list and so fails everywhere, because a checker that could not
check is not a pass.

**Tables and figures are generated from results, never hand-authored.** Tables are emitted
by code from `results.json`; figure scripts may read `results.json` and nothing else. This
closes the hole that, in the predecessor project, let a wrong count reach Table 1 and
survive every check.

## Decisions

| Question | Decision |
|---|---|
| Repository scope | Reusable toolkit; no paper |
| Markdown ↔ Zotero docx | Markdown authoritative, docx regenerated with live citations |
| Enforcement | Hard fail on any unclassified number |
| Analysis stack | R for statistics, Python for tooling; analysis language pluggable |
| Packaging | pip package plus Claude Code plugin |
| Worked example | Synthetic pharmacovigilance disproportionality study |
| Review panels | Composition derived from field and journal; second panel blinded to round one |
| Licence | MIT |
| Reporting guidelines in v1 | STROBE, RECORD, RECORD-PE, CONSORT, SPIRIT, PRISMA, TRIPOD, ARRIVE |
| Tables and figures | Both generated from results; hand-authoring forbidden |
| Author voice | No personal voice to match; generic scientific register |
| English variant | User-configurable, overridden by the journal profile |
| Abstract-only sources | Recorded and flagged in reports; not grounds for failing a build |

## Build order

1. ~~**Contracts.**~~ **Done.** Skeleton, packaging, CI. Schemas for results, ledger,
   attested, authors, paper. An emitter in Python and R with provenance stamping. Gate G1.
2. ~~**The number guarantee.**~~ **Done.** Placeholder syntax and substitution,
   numeric-token classifier, convention allowlist, figure-literal extraction,
   cross-artefact consistency. Gates G2, G3, G8, with the corruption harness below.
3. ~~**Build pipeline.**~~ **Done.** pandoc with `zotero.lua` for live citations, an
   offline mode using the committed `.bib`, emitted tables, figure placement, and gate G7.
4. ~~**Literature ledger.**~~ **Done.** Sources filed by citation key, quote and value
   verified against the stored source, attestations restricted to people, and a skill for
   Chrome-driven retrieval.
5. ~~**Compliance.**~~ **Done.** Journal profiles and reporting checklists as retrieved
   data, with gates G4 and G5 and two retrieval skills. See the note below on why no
   official checklist ships.
6. ~~**Writing quality.**~~ **Done** apart from the pre-analysis design gate. AI-writing
   lint (G6) derived from the Wikipedia essay, methods-drift detection (G9), and skills for
   both.
7. ~~**Review panels.**~~ **Done.** Recorded panels, review records as the contract, a
   blinded second round, and severity that depends on whether a submission is being built.
8. ~~**Example and public documentation.**~~ **Done.** The submission pack, the
   pre-analysis design gate carried over from phase 6, and the worked example throughout.

Phases 1 and 2 carry the guarantee; everything after is additive.

## Provenance depth of literature values

Every literature value carries one of three depths:

| Depth | Meaning | Requires |
|---|---|---|
| `full-text` | extracted from a stored full text | stored source file, locator, verbatim quote |
| `abstract-only` | extracted from a stored abstract | stored abstract file, verbatim quote |
| `user-attested` | the author read a source the toolkit could not retrieve | attester, date, locator, statement |

`full-text` and `abstract-only` live in `literature/ledger.yaml`. **`user-attested` values
live in their own file, `literature/attested.yaml`**, so that the set of numbers resting on
human attestation rather than a stored artefact is trivially auditable — by a co-author, a
reviewer, or the author six months later. Both files feed the same `lit.` namespace, and
G7 reports the three depths separately. Abstract-only status is flagged but never fails a
build; a `user-attested` entry missing its attester or statement does fail.

## The corruption harness

The claim "no stale number" is worth exactly as much as the evidence that the gate catches
one. `tests/test_corruption.py` is therefore adversarial rather than illustrative.

Its headline test takes **every binding in the example manuscript, one at a time, and
replaces it with the literal value it currently resolves to** — then requires that
manuscript to fail. This is the hardest form of the problem, because at the moment of
corruption the number on the page is still *correct*; it is stale only in waiting. A
checker that compares numbers against a backing set passes every one of them. This one
fails every one, because in source a results-derived number may not be a literal at all.
As of the first build: 14 distinct bindings, 14 caught.

The rest of the harness covers the other routes a number goes wrong: a hand-edited results
file, changed or deleted input data, a modified analysis script, a typo in a binding, a
malformed binding, a declared value nothing quotes, a hand-authored table, an edited
figure, a figure script that stopped reading results, one quantity emitted under two names,
and near-miss conventions such as `p < 0.37` that a laxer allowlist would wave through.

## Decisions taken during construction

- **The digest of a results fragment is a `.sha256` sidecar, not a field inside it.**
  Hand-editing the one file the toolkit trusts was otherwise detected by nothing. A field
  inside the fragment would require canonical-JSON agreement between Python and R, which
  float formatting alone will break; "hash the bytes you just wrote" is the same operation
  in every language. This detects accidents, not adversaries, and is documented as such.
- **`display` is resolved at emit time and written into the fragment.** Any consumer in any
  language reads one field and gets the string the prose will show.
- **Axis ticks are declared per figure in a `<name>.guard.yaml` sidecar.** A figure
  legitimately contains numbers that are neither results nor prose conventions. Declaring
  them per figure keeps the exemption small and visible instead of weakening G3 globally.
- **A figure script that ignores the results fails only when its figure prints numbers.**
  A flow diagram has no reason to read results; a figure with numeric annotations whose
  script never opens the results file is drawing them from somewhere unverifiable.
- **The scaffold omits optional fields rather than writing them empty**, so the first
  `check` on a new project reads as a to-do list of real work.

## Figures get three checks, not one

A figure is the easiest place for a stale number to survive: rendered once, looked at
rather than read, and never touched by a prose check. So it is checked three ways.

**The rendered output.** Numeric text in the figure's text layer must match a results
display string or classify as prose would. Axis ticks are declared per figure in
`<name>.guard.yaml`.

**The source.** The classifier runs over the figure script itself, because output checking
alone leaves a hole that is invisible from either side: a script that reads the results
*and also* types one annotation passes the output check, since the typed number equals the
right value today, and passes any script-level check, since the script does read the
results. Two rules apply. Numbers inside string literals are judged exactly as prose, so
`"95% CI"` passes and `"ROR 3.84"` does not. Numbers in code are judged by syntactic
position: a number under a presentation parameter or inside a plotting call is layout,
anything else is a candidate claim. The context comes from a small two-language lexer that
tracks the bracket stack, so `scale_y_log10(breaks = c(0.5, 1, 2))` gives each number the
chain `c > breaks > scale_y_log10` and one lookup settles it.

The presentation list is deliberately narrow. `x`, `y`, `n` and `digits` are **not** on it,
because allowing bare coordinates would allow `data.frame(x = c(1, 2, 3))` — data typed
into a figure script, which gets its own error message.

**A human or model reading the picture (G10).** Gate G10 requires a current review record
per figure. See below.

## Reading the figure

Some errors in figures are invisible to every parser. A truncated axis that makes a small
difference look decisive. A legend naming a series the plot no longer contains. A caption
describing the figure the author meant to make. Every number can trace to the results and
the picture can still mislead.

So the reading is delegated to a model or a person, and `figures/<name>.review.yaml`
records it: who reviewed it, when, seven required checks, findings, and a verdict. G10
enforces what can be enforced mechanically — that a review exists, covered all seven checks,
and applies to the figure as it now stands. **It cannot verify that the review was any
good.** Same bargain as `literature/attested.yaml`.

Two details worth stating plainly, because both were overstated here before.

A per-check `note` is *optional* in the schema, though the schema's own description explains
why it should not be ("a check marked ok with no note is indistinguishable from a check
nobody performed"). It is left optional deliberately — requiring prose produces prose — but
it means the record can be thinner than this paragraph once implied.

And G10 does more than check that the record exists: it reads each finding's own `severity`
and applies it, so a finding recorded as `fail` fails the run and the same observation
recorded as `info` does not. G11 does the same with `severity: major`. That is what "the
record is the contract" means, and it is the one place a model's output can change a
verdict — worth naming, since the README's deterministic-code claim is otherwise absolute.

Two normalisations make review currency workable. Render timestamps and randomly generated
element ids are excluded from the digest, so re-rendering an unchanged figure keeps its
review current while a real change invalidates it. Without that, every build would mark
every review stale, and an author would learn to ignore the gate.

The worked example earned this the hard way. Its first review returned `concerns`: the
manuscript said Figure 1 showed the estimate "against the comparators" and the figure had
one row. Every other gate passed it, because every number in the figure was correct. The
sentence was what was wrong.

## The build

The .docx is regenerated from Markdown every time and never edited or patched. That is what
makes a stale number impossible rather than merely unlikely: nothing is ever carried across
by hand, so there is nothing to forget.

Two modes, and the choice is a fact about the machine rather than a preference:

- **live** — pandoc with Better BibTeX's `zotero.lua`, which queries the running Zotero and
  writes real `ADDIN ZOTERO_ITEM CSL_CITATION` fields that Word's Zotero plugin adopts.
  Verified end to end: both bracketed `[@key]` and narrative `@key` produce fields, the
  latter only once `author-in-text: true` is set in the generated front matter, which is
  the second of the two chores the first pipeline test uncovered.
- **offline** — pandoc `--citeproc` against a committed `literature/references.bib` and a
  CSL style. Citations become formatted text rather than live fields. This is what a
  co-author without Zotero gets, and what CI builds with, and it is why the `.bib` is
  committed rather than exported on demand. `manuscript-guard sync-bib` rewrites the `.bib`
  from Zotero, containing exactly the keys the manuscript cites.

`zotero.lua` is fetched and cached under `build/.cache/` rather than vendored: it belongs to
Better BibTeX and tracks its behaviour, so a pinned copy would go stale.

After a live build the document is reopened and its Zotero fields counted, because the
filter fails quietly when Zotero is closed — the result looks fine until someone clicks
Refresh in Word and every citation vanishes.

CI installs the pandoc version pinned as `MANUSCRIPT_GUARD_REQUIRE_PANDOC` in
`.github/workflows/ci.yml`, and with that variable set the test suite refuses to start
unless that pandoc is on PATH. Until it did, no test job had pandoc: every test that needs
it skipped on every job, and none failed for want of it.

**Tables are emitted, not written.** `em.table(...)` puts a table in the results fragment,
`{{table.key}}` places it, and the build renders a pipe table. A hand-typed table is the
most reliable place for a stale number to survive: long, dull to re-read, never diffed. An
emitted table nothing places is a coverage failure, exactly like an unquoted value.

**Figures are placed, captions are prose.** `{{figure.key}}` resolves to the rendered file,
preferring raster or PDF over SVG because Word's SVG support is uneven and a journal's
production system is worse. The caption stays in the manuscript as ordinary prose, so it is
checked like prose and can carry bindings.

**The header comes from `paper.yaml`, and a manuscript's front matter prints nothing.** The
build strips every source file's YAML block and writes a header of its own with the title,
short title and keywords from `paper.yaml`. A `title:` in the manuscript is compared with
that one and a disagreement warned about (`two-titles`). An `abstract:` there is refused,
by G2 and by the build alike (`front-matter-abstract`), as a block pandoc cannot read is
(`front-matter-unreadable`). G2 reads it, because pandoc prints one, and until 2026-09-26
the build dropped it without a word: the abstract was checked, then left out of the
document, and the word count, which follows the build, let a journal's abstract limit pass
on 0 words. It is refused rather than printed because everything else here already finds
an abstract by its heading: the word count, G4's structured-abstract headings, and the
paragraph identifiers the Word import maps edits back with. Printed from the header, each
would have needed a second place to look, and a co-author's edit to it in Word would have
had no source paragraph to go back to.

The abstract is found by reading the block as pandoc does, with the loader that decides
the block is front matter, and not with G2's reader, which finds a value by its key line.
Read G2's way, a quoted key (`"abstract":`), a quoted value opened on the key's line and
continued below it, or a flow mapping passed `check` and was dropped by the build, though
pandoc prints each of them; and `abstract: null` or `abstract: # to do` was refused,
though pandoc prints nothing for either. Merge keys are followed, because pandoc honours
them: an abstract merged in with `<<: *base` prints. A key is known by its text, as pandoc
knows it, so `"<<": *base` merges too, although PyYAML tags only a plain `<<` as a merge.
Each mapping is visited once, since a chain of mappings each merging the one before it
twice doubles the work of expanding them with each line, and 614 bytes of such front
matter once held `check` for 38 seconds. An abstract pandoc reads as empty is let through,
and so is a key named `abstract` inside another mapping, which pandoc does not take for
the abstract. Any other value, a number or `yes`, is refused rather than guessed about.
PyYAML's composer and pandoc 3.9 were compared on each of these spellings, and on a
duplicated key, where both keep the last.

## Zotero is never on the critical path

Two budgets: a gate waits 20 seconds, an explicit `sync-bib` waits 300. Zotero indexing a
large library can leave `item.search` unanswered for minutes, and a check that hangs is
worse than one reporting "could not read Zotero, using the committed bibliography". A
failure is remembered for the rest of the process, because retrying a 20 second timeout
once per gate turns a two second command into a two minute one.

Pinning can only be checked against Zotero itself, so when Zotero is unreachable that check
downgrades to a warning rather than passing silently.

## The literature chain is verified, not trusted

Every ledger entry stores the value, the sentence that states it, and the source that
sentence came from. Two of the three are machine-checkable, and checking them verifies the
whole chain from manuscript to published sentence without anyone re-reading the paper:

1. **The quote must appear in the stored source.** If it does not, either the source was
   replaced or the quote was reconstructed from memory — which is how a number no paper
   contains ends up cited to one.
2. **The value must appear in the quote.** A sentence that does not state the number it is
   offered as evidence for is not evidence for it. In practice this catches quoting the
   sentence next to the one wanted.

Comparison folds the differences that are not differences: curly quotes, dash widths,
ligatures, non-breaking spaces and line wrapping all differ between a quote copied from a
rendered page and the same sentence extracted from a PDF, and none of them change what was
written. A check whose failures are typographic noise gets switched off. A genuine
paraphrase still fails: dropping "drug-induced" from a quoted sentence is reported.

PDF text comes from poppler's `pdftotext` if present, then `pypdf` if importable, and
otherwise the entry is reported as unverifiable rather than passed. Neither is a hard
dependency: a toolkit that will not install without a PDF stack is a toolkit people do not
install.

## Only a person can sign an attestation

`attested.yaml` exists to record that **a named human read something the toolkit could not
retrieve, and takes responsibility for the value**. A language model cannot take
responsibility, so the gate rejects an `attested_by` naming a model — claude, gpt, gemini,
"an AI assistant" and their relatives are all refused.

This is not decoration. Without it, the one file whose entire purpose is human
accountability is the easiest file in the project for an agent to fill in on the author's
behalf, and the guarantee evaporates silently. The skill instructs the model to draft the
entry, leave `attested_by` empty, and ask.

A statement shorter than eight words also warns: "Read it." records nothing a reader in two
years could act on.

## Compliance is data, not code

Neither a journal profile nor a reporting checklist is compiled into the tool. Both are
YAML retrieved from the source that owns them and stamped with the date it was read, and
the reasoning is the same in each case.

**Journal guidelines change without announcement.** A limit hard-coded in the tool would
eventually be wrong, and wrong *silently* — the worst kind. Profiles state only what the
journal's page actually says; an absent limit is not checked, because a guessed one
produces confident failures about a rule that does not exist. A profile over a year old
warns. Switching journals after a rejection means writing a second profile and reading the
resulting failure list, which is the reformatting job itemised.

**A required statement counts where it prints as one.** A profile's statement patterns, and
a structured abstract's required headings, are searched with HTML comments and fenced code
blanked (`scannable`). A comment prints nothing, and a listing prints its lines as code, not
as a declaration. `# Funding` is a heading in Markdown and a comment in R and Python, and
inside either it met the funding statement of a paper that had none. A statement written in
a fenced block therefore does not count, and no journal takes one written as code. The
blanking is close to what pandoc prints but not the same; where they differ is under Known
gaps.

**Checklists are transcribed from their official documents, never written from memory.**
Item text that is approximately right produces confident coverage of the wrong things, and
approximately-right official wording inside a toolkit whose whole argument is that
approximately right is not good enough would undermine the thing being built.

So a checklist is a **recipe plus a document**. The recipe says where the items sit — which
table, which columns, how sub-items are written — and `manuscript-guard transcribe` turns
the guideline's own file into a profile. The transcription is a deterministic function of
the document and the recipe: re-run it and you get the same profile; run it against a
revised checklist and the diff is the revision. Every item is then verified to appear
verbatim in the document, using the same comparison the literature ledger uses for a quote.

Thirteen checklists have recipes: STROBE (34 items), RECORD (13), RECORD-PE (15), CONSORT
(41), SPIRIT 2025 (53), PRISMA 2020 (42) and its abstracts checklist (12), READUS-PV (32)
and its abstracts checklist (12), TRIPOD in its three variants (31 development, 31
validation, 37 both), and ARRIVE 2.0 (21). READUS-PV is the guideline for disproportionality
analyses of spontaneous reports, and is more directly applicable to signal-detection work
than STROBE.

**The repository ships recipes, not transcribed text.** Licences were read on 2026-08-03 and
are recorded per recipe and in [ATTRIBUTION.md](ATTRIBUTION.md). The picture settles the
design: RECORD is explicitly CC BY, STROBE and ARRIVE are CC BY through their statement
papers, **READUS-PV is CC BY-NC**, and four state no reuse licence at all. A repository
shipping their text would have to satisfy the strictest of them, and one of them is
non-commercial.

**Fetching is not redistributing.** When the tool downloads from the publisher's own URL
because the user asked it to, the user obtains the document exactly as they would by
clicking the link, and the project distributes nothing. That is the structure:
`manuscript-guard fetch` retrieves, `transcribe` builds the profile locally, and both the
documents and the generated profiles are gitignored.

Three decisions follow from it:

- **Never during `pip install`.** Installs run offline in CI and sandboxes, network
  side-effects break reproducible builds, and a silent download means nobody reads the
  terms. Fetching is an explicit command.
- **The licence is printed before the download**, not filed away afterwards.
- **The document is checksummed against the recipe.** A recipe encodes which table and which
  columns hold the items, so a silently revised checklist would otherwise produce a
  plausible wrong transcription. A mismatch stops the build and names the source URL;
  `--allow-changed` overrides it deliberately.

A uniform "never redistribute" rule is kept even for the CC BY ones. Per-guideline
judgements have to be re-made whenever a guideline is revised or a new one is added, and one
command is a small price for never having to reason about it again.

A guideline named in `paper.yaml` with no retrieved checklist **fails loudly** rather than
passing quietly.

The example carries an openly invented journal and checklist, labelled as such in both
files, exactly as it carries invented literature sources.

### What the verification caught

Writing the transcriber and trusting it would have been the obvious mistake. Verification
caught two parser bugs that produced plausible, wrong output:

- **Continuation rows were read as section headings.** STROBE writes item 1 as two rows, the
  second with only the text cell filled. Treating that as a heading dropped every sub-item:
  the first run produced 22 items where the document has 34 rows, and looked right, because
  STROBE does have 22 numbered items.
- **Multi-item cells were truncated.** RECORD packs three extension items into one cell
  ("RECORD 6.1: … 6.2: … 6.3: …"). Reading only the first gave 8 items instead of 13.

A third bug was found by verification failing on correct transcriptions: `document_text`
joined Word runs with spaces, and Word splits runs mid-word, so "study's" became "study 's"
and true quotes looked false.

### Not every checklist can be verified equally

ARRIVE 2.0 publishes no Word checklist. Both its sets are printed side by side on one page
of a PDF, so there is no table to read — only a visual grid, recovered by cutting the page
at the column boundary and each column into topic, number and text sub-columns.

That path cannot support the same verification. Topic words wrap into the left margin of
continuation lines and land *between* an item's own text fragments, so an item's full text
is genuinely not contiguous in the page however correct the extraction. Only each item's
**opening clause** is verified, which still catches a mis-cut column or an item attributed
to the wrong number, but not a wrongly assembled tail.

Rather than let that pass unmarked, every profile now records a `verification` field, and
ARRIVE's says `opening clause only (column-laid-out PDF)`. Two different guarantees should
not look identical in the output.

Two smaller decisions fell out of this:

- **`reporting_guideline` is no longer a closed enumeration.** Guidelines are revised,
  extensions appear, and a schema refusing CHEERS or SQUIRE would be wrong about the world
  rather than about the project.
- **"n/a" is rejected as a reason.** A checklist item excluded needs a reason a reviewer
  could read — "no interventions were assigned" — because a reviewer does read this file.

## Word counting is a stated rule

A limit is only checkable if both sides agree what is counted, and journals rarely say. The
rule used is written down and the count reported beside the limit: whitespace-separated
tokens after citations, tables, images, code and markup are removed; abstract and
references counted separately; headings counted, because they are printed, and their
attribute blocks (`{#sec-methods}`, `{-}`) not, because pandoc does not print them. Counting
is done on the source rather than the built document, so a binding counts as one word
whatever it resolves to and the count does not move when the analysis is re-run.

The YAML front matter that opens a file is not counted, rendered keys included. The build
strips every file's block and prints the title from `paper.yaml`, so none of it is in the document a limit is
about, and a journal counts a title and an abstract against limits of their own anyway. An
abstract counts when it is written under an Abstract heading, which is where the build
prints one. One written in the front matter is refused rather than counted as 0 words (see
the build). Until 2026-09-24 the block counted as main text: `split_sections` trimmed the
text before the first heading, the closing `---` lost the newline the front-matter pattern
needs, and the example's title line took its main text from 557 words to 573. G4 had a second
route to the same mistake. It reads the main text as one string joined from every file, so
only the first file's block was at the top, and a later file's closing `---` underlined its
last YAML line into a heading: `title: Methods of the online appendix` satisfied a required
Methods section. The title page declares the count G4 checks, from the same text.

## The AI-writing lint measures rate, not presence

The rules come from the English Wikipedia essay "Signs of AI writing", read 2026-08-03.
Much of that essay is Wikipedia-specific — wikitext, categories, edit summaries — and is
dropped. What survives is vocabulary, sentence shape, formatting and tone.

**What the gate claims is narrow: it detects habits, not authorship.** A person who writes
"it is important to note" is flagged, and a model that avoids every listed construction is
not. It is a style check against a well-catalogued target, and calling it a detector would
be a lie a user could act on.

The adaptation that makes it usable in science is measuring most rules as a **rate per 1000
words** rather than flagging each occurrence. "Robust" describes a standard error,
"significant" has a technical meaning, "key" and "highlight" are unremarkable once. Six
"crucial"s in four hundred words is a tell; one is a word. A lint that flags `dpi=300` in a
figure script gets switched off, and the same is true of one that flags robust standard
errors.

Three severities:

- **fail** — model output artefacts (`oaicite`, `[cite: 1]`, "as of my last training data",
  unfilled placeholders). No innocent reading; these must never reach a submission.
- **warn** — constructions with a defensible use but a strong association. Reported with the
  reason so an author can disagree and move on.
- **warn on rate** — ordinary words, counted.

Two refinements came from running it on this project's own example. Structured-abstract
labels are bold by journal requirement, so counting them flagged the journal's house style;
they are exempt. And technical senses are exempt by pattern, so "robust standard errors"
does not count towards the vocabulary rate.

**Vague attribution gets the one check an encyclopedia cannot use.** "Studies have shown" is
reported only when no citation sits within 240 characters, because in a manuscript the fix
is a reference rather than a rewrite.

## Methods drift is a reconciliation ledger

Methods sections go stale in a specific way: the analysis changes, and nothing forces the
prose to follow. Nobody re-reads their own Methods.

No checker can read code and prose and decide whether they agree. G9 therefore records
something it *can* verify — that a person read the Methods against the analysis, and
whether anything has changed since. `methods.lock` holds a digest of every analysis file as
it stood at that moment; the gate compares and names **which files** changed, so the
re-reading is targeted rather than a vague instruction to check everything.

Digests, not timestamps: copying a tree or re-saving a file is not a change.

The claim is modest and true. It does not verify that the Methods are correct. It verifies
that somebody looked, and that nothing has moved since they did — the same bargain as the
figure review and the literature attestation. Reconciling without reading makes the file a
lie, and the skill says so in those words, because a machine-checkable lie is worse than no
check.

The lock can also carry parameters that must appear in the prose — the significance
threshold, the software version. Presence, not correctness, but those are exactly what a
reviewer queries and exactly what is left behind when an analysis is redone.

## Review panels: the record is the contract

Every other gate checks a property of the text. G11 checks that somebody competent
disagreed with it, or failed to, on the record.

The unit is a **review record**, not an agent. A model can produce one in minutes, a
co-author can write one by hand, and the gate treats them identically — which is what keeps
the toolkit usable by someone who has never run an agent. Agents are one way to fill the
records, not the mechanism.

Two choices carry most of the value:

**The panel is written down, with reasons.** A panel's composition decides what it can see;
three methodologists will not notice that the clinical framing is wrong. Recording who was
asked and why makes the gaps visible while there is still time to fill them. Composition is
derived per paper from the design, the reporting guideline and the target journal.

**The second panel is blinded by default.** A second round that reads the first round's
findings inherits its sense of what matters, and the errors worth catching in round two are
exactly the ones round one was not looking for. An unblinded later round warns.

**Severity depends on what is being built.** An author mid-draft must be able to produce a
document to read, so ordinary builds warn. `--submission` raises every review warning to a
failure: the version that goes to a journal should not carry unanswered major findings.
That flag is the only place in the toolkit where a gate's severity is contextual, and it
exists because the alternative — blocking every build on a complete two-round review — would
make the gate something to switch off.

**An override is a legitimate answer.** A major finding needs a resolution saying what was
done, or an `overridden` saying why it was not. Recording the reason turns it from an
oversight into a decision, and it is the thing you want when a real reviewer asks the same
question. Silence is the only unacceptable answer.

Editing the manuscript marks the reviews stale, which is correct: a review of the old
Results is not a review of the new ones. **What it marks stale is scoped to what each
reviewer read.** The first version hashed every byte of every manuscript file together, so
fixing a typo in the Discussion voided both completed rounds, including the
biostatistician's read of the Methods — and since `review-stale` is a hard failure at
submission, the harshest check in the toolkit fired at the moment an author is copy-editing.
A record may now carry `file_sha256`, the files it actually read, from `manuscript-guard
review --files`; it goes stale when one of those moves, and the finding names the file. A
record without the key means the whole manuscript, so older records keep the behaviour their
writer intended.

That scoping is only honest because of its companion, `review-uncovered`: a round is
incomplete while some manuscript file is on nobody's list. Without it, trimming the map
would have been a way to review the Methods and pass — the same fix-opens-the-next-hole
pattern that three review rounds kept finding, so the two landed together.

**A revision is answered by a further round, which supersedes the rounds before it.**
`review --record` will not re-stamp a record, because the digest is the only thing
separating "somebody read this version" from "somebody read a version", and it tells the
author to record the new reading as a further round instead. Until 2026-09-24 that advice
led nowhere: the earlier records stayed `review-stale`, and a file added in revision left
every earlier round `review-uncovered`, so `check --submission` could pass only after
somebody hand-edited a digest or deleted a round. Now, once a later round is complete and
current, each earlier round that is stale or uncovered is reported as `review-superseded`,
an INFO naming the round that superseded it. It still counts towards `rounds_required`,
because it was a complete reading of the paper it read, and its unanswered major findings
still fail the submission: history is not absolution. A round that never finished is not
rescued, since a missing record is a remit nobody answered, whenever that was. The author
chose this over the alternatives: re-reading every round after every change (the strongest
guarantee, and the one most likely to be switched off), superseding only across a journal's
revision round (which left copy-edits before the first submission at the same dead end), and
no change.

The worked example carries a real two-round panel. Round one found that the paper had no
case definition, no mention of duplicate records, and no contingency table for a result that
was a single ratio; all three were fixed, and the manuscript is better for it. Round two,
blinded and differently composed, found the remaining soft spots. Two findings are recorded
as deliberate overrides rather than fixed, because the honest answer was that the synthetic
data do not support what the reviewer wanted.

## The submission pack writes nothing twice

Everything a journal asks for except the covering letter is already recorded in the project.
`authors.yaml` becomes the title page, the CRediT statement and the declarations; the
reporting completion file is copied as it stands; the build produces the document. Nothing
is transcribed, so the title page cannot list an author who left two revisions ago and the
funding statement cannot contradict the acknowledgements.

Two places where the generator says something rather than papering over it. An author with
no CRediT roles produces a statement saying so, because most journals now require them. An
author whose `competing_interests` field is empty is listed as having made **no
declaration** — an empty field is not a declaration of none, and journals ask per author.

The manifest records every file with its sha256, because six months later "which version
did the journal actually get" has no reliable answer otherwise.

The pack refuses to assemble while `check --submission` fails. That is what the check is
for.

The covering letter is deliberately not generated. It is the one part addressed to a
particular editor about a particular paper at a particular moment, and a generated one reads
exactly like a generated one.

## The design gate warns and never blocks

Writing down what you intended before you did it is the strongest single thing available for
the credibility of a result — not because deviating is wrong, but because a deviation that
was declared is a decision, and one nobody recorded is indistinguishable from having tried
several things and reported the best.

Blocking would be the stronger discipline and would be unworkable. Exploratory work is real
work, and a gate that prevents you writing code until a plan is agreed is a gate that gets
bypassed on the first afternoon it costs something. So G12 warns: when analysis code exists
with no plan behind it, and when a plan's section is a heading with nothing under it. A
"Deviations from the plan" heading followed by nothing is the common case, and naming it is
most of the value.

## Stages: not every gate binds on day one

The first version of `check` ran all twelve gates unconditionally, which meant that someone
still writing their analysis was told the figures were unreviewed, no journal had been
chosen and the reporting checklist was empty. All true, none useful, and collectively the
strongest possible argument for not running the check again.

Each finding now declares the stage at which it starts to fail: `design`, `analysis`,
`drafting`, `internal-review`, `submission`. The stage comes from `paper.yaml` or from
`--stage`; `--submission` is shorthand for the last one.

Three rules keep this from becoming a way to hide problems.

**Every gate runs at every stage.** Only severity changes. A deferred finding is printed as
`INFO`, tagged `[not due until drafting]`, counted, and summarised at the end as *"3 findings
not due yet … They are listed above as INFO, not hidden."* A check that quietly stopped
looking would be worse than no check.

**Unlisted codes bind immediately.** A finding the policy does not know about fails at every
stage, so adding a gate cannot accidentally make it optional. The author of a gate has to
decide, in `policy.py`, when it should start to matter.

**Deferred means INFO, not WARN.** A warning is something to look at now; these are things
that are not yet due. Mixing them would drown the warnings that matter.

Writing the policy exposed two mistakes in my own placement. Results were bound at
`analysis`, which is wrong — results appear at the *end* of the analysis stage, not its
start — and an unfinished `authors.yaml` was being reported as a malformed contract when it
is a to-do list. The second needed a distinct finding code so that a genuinely broken
authors file and a merely unfinished one could be told apart.

The effect is that `manuscript-guard init` followed by a first analysis script now reports
zero failures at `design` and `analysis`, with the outstanding work listed as not yet due,
and the same items fail from `drafting` onwards.

## The plugin: skills for judgement, hooks for the moment of the mistake

The original brief asked for skills **and hooks**. The skills came first and the hooks were
outstanding for seven phases, which was the wrong order: a skill helps when you remember to
invoke it, and a hook helps when you do not.

Four hooks, chosen because each catches something at the only moment it is cheap to catch:

- **Before a write**, refuse edits to `results/`, `build/` and generated checklist profiles.
  This is the direct mechanical form of "the latest results are always used": the file
  cannot be hand-edited, so it cannot drift from the analysis that wrote it. G1 detects the
  edit afterwards; the hook prevents it.
- **After a write**, classify the numbers in the manuscript file just saved. The same check
  G2 performs, but while the author is still in the paragraph rather than at the next build.
- **After editing an analysis file**, say the results are stale and the Methods may no
  longer describe the code.
- **Before a submission-shaped shell command**, run the submission check and block on
  failure.

That last one carries a specific lesson. It matches the **whole command string**, with no
permission-rule prefix filter, because `cd example && manuscript-guard submit` and
`FOO=1 manuscript-guard submit` both defeat a prefix rule — which is precisely how a
submission build slipped past the equivalent guard in the predecessor project. The cost is
that the hook fires on every Bash call, so it has its own console script
(`manuscript-guard-hook`) that imports nothing heavy until it knows it has work: 152 ms for
the no-op path against roughly 400 ms through the full CLI.

**A hook never breaks the session.** Every handler swallows unexpected errors and exits 0.
A guard that crashes on a half-configured project gets removed by the author, and the guards
that were working go with it.

**A hook blocks only what is unambiguous.** Writing a machine-written results file is always
wrong. Prose that trips the AI-writing lint is not, so nothing in G6 is enforced this way.

## Auditing existing papers, and saying what the audit is worth

`check` works because manuscript source contains bindings: a results-derived number cannot
be written as a literal, so nothing passes by coincidence. An existing paper has no
bindings. Every number is a literal, and the only available question is the weak one — does
this number appear anywhere in the outputs?

That is precisely the set-membership check this project's predecessor was built on, and
which was measured and found near-vacuous: with the analysis outputs as the backing set,
100% of integers up to 100 and 97% up to 1000 already matched, and of fifteen deliberately
corrupted headline numbers it detected none while reporting success.

So `manuscript-guard audit` reports two things, and the second is not optional: the numbers
matching nothing, **and what a match is worth in this particular project**, computed from
the backing set the user actually supplied. On the worked example, pointed at the raw data,
it reports 100% chance-match on every integer and says a match means almost nothing. Pointed
at the analysis outputs, 24%. A clean report cannot be mistaken for a clean paper.

Making it usable on real documents needed four things, three of them lessons from the
predecessor:

- **Table cells kept apart.** Word stores a row with no separator between cells, so a naive
  read turns `39 | 20 | 26 | 16` into 39,202,616 and silently skips every table. A wrong
  count in Table 1 survived every check for exactly that reason.
- **Tracked changes resolved.** A document under review holds both the old text and the new;
  reading it raw reports corrections as errors and misses what will be published. Text moved
  away goes with the deletions, and so does a deleted line break or tab: read as a space, it
  parted a minus from its number. A paragraph whose mark was deleted or moved away runs on
  into the next one; read as two lines, "-0.5" and "1" matched two outputs where the paper
  prints -0.51. The joined line takes the last paragraph's style, and so ends a reference
  list only if that one is a heading. That is what Word 16 shows once the change is
  accepted: when it deletes a mark itself it first copies the first paragraph's style onto
  the second, keeping the old one in `w:pPrChange` (verified 2026-09-24). A text box is
  read after the paragraph holding it, not where it is anchored, which split that paragraph
  in two.
- **The bibliography dropped.** Recognised by heading where there is one and by entry shape
  where there is not (author-year, or the numbered styles' `2019;393:100`), because citeproc
  appends a reference list with no heading to cut at. It ends at the next heading, so an
  appendix or a footnote after it is still read. Otherwise every volume number and page
  range is reported. A heading is read without the attribute block pandoc takes off it:
  `# References {-}`, the usual way to leave the list unnumbered, was no heading at all, so
  nothing was cut and a book or a web page in the list had every number reported. On a line
  nothing marks as a heading the braces are printed, and it is not one.
- **Rendered citations classified.** In source a citation is `[@key]` and gets masked; in a
  built document it has already become "(Smith and Jones 2019)", and without a rule for that
  every citation in the paper is an unexplained number.

Verified end to end: the example's built document audits clean against its own outputs, and
one digit changed in the reporting odds ratio is reported with its line and context.

## What an adversarial review found, 2026-08-03

Four reviews were run against the finished toolkit — security, Python correctness,
architecture, and an adversarial one that built a project and attacked it 56 ways. Every
claim below was reproduced against the code before anything was changed; several other
claims were rejected on the same test. The defects clustered, and the cluster is worth
naming, because it is the shape of mistake this kind of tool makes.

**Nine of the eleven fixed defects were a rule matching a shape instead of a value.**
`conventions.yaml` says in its own header that a pattern must be pinned to specific
conventional values, "because a rule matching `p < <any number>` would wave through every
reported p-value." Five rules broke their own file's rule:

| rule | matched | so this passed |
|---|---|---|
| `rate-denominator` | `per \d[\d\s,]*` | `12 per 83,214 patients treated` |
| `age-band` | `\d+\+\s*(?:years?)?` — unit optional | `enrolled 500+ patients` |
| `categorical-label` | `arm\|cohort\|grade… \d+` | `in the exposed arm 47 hepatic events` |
| `time-label` | `years?… \d+` | `over the study years 1204 reports` |
| `author-year-citation` | a whole parenthetical containing a year | `(Smith 2019, n = 412)` |

Each is now bounded to the magnitudes a label can actually have, and the last is marked
`audit_only`: it exists to read a document citeproc has already rendered, and in manuscript
source — where citations are `[@key]` and masked — it bought nothing and cost the gate.

**Three defects made the tool report less than it checked, or check less than it claimed.**

- `find_atoms` split on `\S+`, but `mask()` writes NUL to preserve offsets, and NUL is not
  whitespace. So `3.84[@smith2020]` was one run, the run contained NUL, and the whole run
  was discarded — the visible 3.84 with it. Any value written hard against a citation, a
  footnote, inline code or a pandoc attribute was invisible to G2. Two reviewers found this
  independently.
- The twelve gates sat behind `if contract_report.ok and load_report.ok`. A project with no
  results yet — the ordinary state at `design` and `analysis` — failed that condition, so
  none of them ran, and the run printed `0 failing, 0 warnings`. The stage-policy test
  asserting that an early project is not buried in failures passed *because nothing was
  checked*. It now has a companion that asserts G2 and G6 actually ran.
- YAML front matter was masked whole. Pandoc renders `title` and `abstract` from it, so the
  most-read part of the paper was outside every check. Rendered keys are now read; `lang`,
  `zotero` and the rest of the machinery stay masked. (Later: a `---` followed by a blank
  line was taken for the opening of front matter too. Pandoc prints it as a horizontal rule,
  with the prose after it, which went unread up to the next `---`. The build found the end
  of the front matter with a pattern of its own, and the two had to be made one: fixed in
  the gates alone, G2 read a `## Methods` heading that the build still stripped, and
  `p < 0.001` under it passed as the alpha chosen in advance. There is one pattern now, and
  `test_pandoc_agreement.py` holds it to pandoc's reading. Every reader also applies it to
  the text as written: the heading scan blanked HTML comments first, so a comment on the
  YAML's first line read as a blank one and the front matter went unrecognised. And nothing
  opened in the front matter closes in the body, as pandoc reads it: a `<!--` in a title ran
  on to the next `-->` in the body, and a fence opener in an abstract paired with a fence
  below, hiding everything between from G2 and the audit, and the bindings between from
  G2's binding checks. The masking, `explain`, G2's fence and binding readers and the
  heading scan all stop at `front_matter_end`; all but the binding reader also look for
  fences on each side of it. What is still open is under Known gaps.
  Later still: the one pattern counts a block only where pandoc keeps it as metadata, so a
  header opening on an HTML comment is not front matter at all, and pandoc refuses it; see
  "Front matter closed by `...` took the body with it" under Known gaps.)

**Two were the same value compared the wrong way.**

- `contains(quote, display)` is a substring test, so a ledger value of `3.4` was accepted
  against a verbatim quote reading `13.42`. The manuscript could then attribute an ROR of
  3.4 to a paper reporting 13.42 — a misquotation of a real source, which is worse than an
  unsourced number because it carries a citation and looks checked. G7 now requires the
  value as a whole numeric token.
- `_judge_string_number` matched a figure script's numeric literal to candidate atoms by
  digit string rather than by position, so `ax.annotate("OR 3", …)  # cf. Table 3` cleared
  the hardcoded annotation using the comment's structural `Table 3`.

**And three were about the tool's own claims rather than its logic.**

- `--submission` and `--stage submission` gave different verdicts, because G11's severity
  came from the raw flag while everything else came from the resolved stage. A project
  declaring `stage: submission` in `paper.yaml` — the natural thing to write when
  submitting — never had the review gate enforced by `check` at all.
- `no-digest` was a warning. A fragment with no sidecar is one no emitter wrote, and while
  this warned, a hand-written `results/national.json` with a fabricated estimate and
  interval passed `check --submission` cleanly. It is a failure from `analysis` on.
- `pip install manuscript-guard` shipped no recipes. They lived at the repository root and
  were resolved as `parents[2]`, which from `site-packages/manuscript_guard/` is
  `<venv>/Lib`. `manuscript-guard fetch STROBE`, the second command in the README's own
  walkthrough, answered `no recipe for 'STROBE'` for everyone who installed as documented.
  Recipes now live inside the package; downloads and generated profiles go to the project,
  never into `site-packages`.

The R emitter also wrote CRLF on Windows — `writeLines(x, path)` opens a text connection and
`useBytes = TRUE` does not change that — so an R analysis produced a byte-different fragment
per platform, and the digest that guarantees the fragment reported `results-edited` on a file
nobody had touched.

Every one of these has a regression test naming the escape it closes.

## Round two, 2026-08-03

A second adversarial pass, run against the machinery the first round produced. Three
reviewers again; every claim reproduced before anything changed. The pattern this time was
narrower and more uncomfortable than the first: **most of what broke was a consequence of a
fix, not of the original code.**

- Fenced code stopped being masked, because it renders. `#` is a comment character. So an
  ordinary `# Methods` comment in a Python listing became a level-1 heading, popped the real
  `## Methods`, and made everything after it — including the Results — read as Methods. A
  fabricated `p < 0.001` in the Results was then accepted as the pre-specified alpha. An
  HTML comment did the same thing while being invisible in the rendered document. Heading
  detection now runs over text with fences and comments blanked.
- `p < 0.05` became Methods-only, and the heading test ended in `\b` — a prefix match. So
  a Results subsection called "Protocol deviations" or "Design of the sub-study" re-admitted
  every threshold rule beneath it. Anchored at both ends now. (Later: anchored, a title that
  kept its pandoc attribute block was another word. `# Results {#sec-results}` was not
  Results, so a "Sensitivity analyses" subsection under it made a reported `p < 0.001` the
  alpha chosen in advance. A title is now read without its attribute block, backslash
  escapes in its values included. Other markup stays: `# **Results**` is not Results.)
- Table cells were classified with no section at all, which meant every `methods_only` rule
  applied — in the one place a *reported* p-value is most likely to be typed.
- `display=` was checked against its value, so the same fabrication moved one line across
  and went out as a **string value**: `em.value("ror.headline", "12.34 (95% CI 8.00 to
  19.00)")` published an estimate and an interval through an ordinary binding, with every
  gate green. String values now have to be labels or be traceable.
- The display check itself computed its tolerance from the mantissa and ignored the
  exponent, so for any small magnitude it was a no-op: a value of 1.2e-6 accepted a display
  of "1e-2".

Two more were original, and both are the same shape as the citation bug the first round
missed:

- **Numbers in a citation suffix rendered but were masked.** The mask covered the whole
  bracket, so `[@smith2019, which reported an ROR of 9.99 (95% CI 7.10 to 14.02)]` printed
  every number and no gate read any of them. This is ordinary pandoc usage, and it is the
  worst case in the whole design — a fabricated value carrying a citation. The mask now
  covers the citation *key*; a `citation-locator` rule handles the `p. 33` that legitimately
  lives in a bracket. An atom ends at the `]` that closes a bracket opened before it, so
  punctuation written hard against a citation does not join its locator: `[p. 3]/` was the
  unbound atom `3]/`, and `import` writes that when a co-author deletes the words between a
  citation and a value. The bracket's contents are still read: masking a narrative
  citation's bracket would hide a value in its suffix, `@key [reported 9.99]`, as masking a
  bracketed citation whole once hid the one in `[@key, which reported 9.99]`. The audit's
  own rule for a printed marker such as `[12]` no longer takes a `]` before it: with one,
  `3.40][12]` was a single match, and a bound closed by a bracket and written hard against
  the marker went unaudited. A value glued to the marker, and a bracketed whole-number
  interval after its value, are audited too now; see Known gaps.
- **Table captions and column headers were checked by nothing** — not by the emitter, not by
  `verify`. Both render with the table.

And `verify` had three of its own, of which one was serious enough to invalidate the
command: see its module docstring for what it now does and does not prove, and the Known
gaps below for what remains.

## A rule names values, not shapes

The classifier's allowlists are the one place where being generous is the same as being
wrong, and the same mistake has now been made eight times: a rule written to match a
*shape* rather than to name specific *values*, which then swallows a real measurement.
`rate-denominator` took any digit run after "per". `age-band` made the unit optional.
`categorical-label` and `time-label` took any number after a keyword. `author-year-citation`
spanned a whole parenthetical. `software-version` was narrowed from `\d+\.\d+` — which had
classified an odds ratio of 3.84 — to "three or more components", and promptly absorbed
`2.10-7.02`, which is how a confidence interval is written in this field.

Every one of those was caught by a person reading the regex, never by a test, because each
rule only ever had positive cases. `tests/data/rule_cases.yaml` now carries `accepts` and
`rejects` for every shipped rule, and `tests/test_rules.py` fails the build if any rule
lacks a negative case — so a rule cannot be added without someone writing down what it must
not do. Negative cases are checked against the *whole* rule set rather than their own rule,
because `2.10-7.02` was absorbed by `software-version`, which nobody would have thought to
test.

There is one exception to "name the values", and it is worth being precise about why.
`alphanumeric-identifier` matches a general shape — one to three letters followed by digits
— and is safe not by enumeration but by construction: **nothing that begins with a letter is
a quantity.** It covers ICD-10 `K71.0`, ATC `L01XC`, trial registrations `NCT01234567`, and
the named disproportionality statistics `IC025` and `EB05`, and it cannot absorb a
measurement because a measurement is not written that way. Rules that match digits get no
such licence.

A realistic pharmacovigilance Methods section produced 27 findings, 25 of them false: coding
systems, the null value of a ratio and the published signal criteria all read as unexplained
numbers. That is the failure mode that gets a gate switched off, and it mattered more than
any individual rule. What fixed it was four rules — the identifier rule above,
`coding-system-code`, `ratio-null-value` and `disproportionality-criterion` — each written
so that the numbers a paper is actually claiming stay unbound. `IC025 > 0` is a criterion;
`IC025 was 1.42` is a finding. The Methods section now classifies completely and the
Results section is untouched.

Two of them needed care about *span* rather than value. A rule matching from "ROR" through
"excluded 1" would also cover the interval in between — `the ROR (1.02 to 3.84) excluded 1`
— and file both bounds, the actual result, as conventional. `ratio-null-value` therefore
anchors on the comparison word and stops at the end of the clause, which is also what
separates "the interval excluded 1" from "the cohort excluded 1 patient": a null value ends
its clause, a count is followed by what it counts. `coding-system-code` has to reach, since
real prose writes "coded with MedDRA version 26.1; the preferred term 10019663" — so the
bridge between the system name and the code is a whitelist of punctuation, version numbers
and function words. Nothing a measurement can be written as is allowed to sit in it.

Dates needed no rule at all. A date already binds as one unit, which is what a study period
should do: `em.value("period.start", "2015-01-01", display="1 January 2015")` and
`{{results.period.start}}`. The reported study period ought to be the data's actual range,
so making it traceable is the point rather than the friction — but the finding's hint now
says that, instead of telling an author to bind a year to a result.

## The table rule lives in the fragment, not in the emitter

"Tables are emitted, not written" was, for a while, a check inside the Python emitter and
nowhere else. That is a guarantee with a hole the size of a language: a rule enforced in one
emitter is a rule an author steps around by switching to another, and the results fragment
is supposed to be the contract. It was also unverifiable after the fact — edit a fragment,
re-sign it, and the cell was never looked at again.

The rule now lives in `tables.py` and runs twice. At emit time it raises, naming the call
just made, because a message about the line you are writing is worth more than a finding two
commands later. In G2 it reports findings about whatever is on disk, whoever wrote it. One
implementation, so the two cannot drift.

That required the fragment to say which cells the emitter produced, because a composed cell
and a typed one are the same characters by the time anyone reads the file. The `composed`
block records the cell, the literal part of its template, and the displays derived for it.
Plain numeric cells are recorded the same way: only the emitter knew it had formatted them,
and the tempting shortcut — let the gate accept any cell that is a single number — waves
through a 9999 typed straight into the file.

The block is a record, not a licence. Its literal text is still checked, so adding a
`composed` entry beside a typed cell does not launder it; three corruption tests do exactly
that and are caught.

With the rule off the emitter, the R package could grow `table()`, `cell()` and
`code_list()` without weakening anything, and a test asserts that the same table written in
both languages produces the same `tables` and `code_lists` blocks. It found a divergence on
its first run: R had no branch for comparator displays, so `<0.001` — a p-value too small to
state — was legal in Python and an error in R. The R function carrying a docstring promising
to mirror the Python one had been wrong for as long as it had existed, which is what such a
promise is worth without a test that exercises both on the same input.

## Round four, 2026-08-04

Four reviewers, three of which ran their own reproductions. The domain reviewer had no
shell, so every one of its fourteen claims was executed here before being acted on; all
fourteen held. The pattern of this round is worth naming: **most of what it found was in
code written the same day**, by the fixes for round three.

**The composed-cell exemption verified nothing.** It checked the *declared* literal instead
of the cell, so an entry declaring an empty literal exempted whatever the cell actually
said — and `Verbatim`, whose own docstring claimed a script could not build one, was an
ordinary importable dataclass. `check` passed on a table cell reading "True mortality
4281003.55% (fabricated)". Separately, `parts` were folded into one project-wide allowlist,
so a phantom entry in a table with no rows whitelisted its strings in another fragment.
DESIGN had already called this "verified rather than trusted". It was not. It is now: the
fragment records the template, the gate rebuilds the cell from template and parts and
requires the result to equal the text on the page, and a code-list cell — which holds no
number the emitter derived — is checked against the code list published beside it.

**A regression from this same day's performance work.** `$` in `ratio-null-value` had meant
end-of-string inside a 160-character window; under the `re.MULTILINE` the document-wide scan
needs, it came to mean end-of-line. Every manuscript here is hard-wrapped, so "...that
excluded 1\npatient with missing data..." read as the null value of a ratio because of where
an editor wrapped. A value passing by coincidence, in the file whose header says that cannot
happen. `\Z` now.

**Five rule leaks, four of them the shape-not-value mistake yet again**, and one worse:
`is_methods` matched *any* heading in the chain, so a Results subsection called "Sensitivity
analyses" — which most pharmacoepidemiology papers have — re-admitted every `methods_only`
rule, and a reported `p < 0.001` classified as the pre-specified threshold. That is precisely
the failure `methods_only` was built to close, reintroduced through the chain rather than
through the heading text. A Methods-like heading now counts only while no ancestor is a
section that reports what happened.

**And the worked example named the wrong guideline.** It claimed STROBE and RECORD-PE;
RECORD-PE is for routinely collected health data and the example is a spontaneous-report
disproportionality study, so the guideline that applies is READUS-PV. It declared neither in
`reporting_guideline:`, used `p < 0.05` as a decision rule, and never demonstrated
`code_list()`. Every new user copies that file. The deeper fault was that **no gate read the
sentence**: an adherence claim is a claim about the paper's own conduct, which makes it worse
than an unbound number, and nothing reconciled it with the checklist actually completed. G5
does now, sentence by sentence, over masked text — so a guideline named in a comment is a
note rather than a claim.

## The annotated copy: four colours, and yellow is not green

`check` produces a verdict. It does not let a co-author, a supervisor or a reviewer *see*
why any individual number is trusted, and "the tool says it is fine" is not a thing a
careful reader should have to accept. `build --annotated` writes
`manuscript.annotated.docx`: every number highlighted by what backs it, carrying a link.
Hover it in Word and the provenance appears; click it and you land on its row in the
provenance appendix. Figures get a contact sheet in the same file — the picture, the values
declared presentational and why, and the record of the person who reviewed it.

**Four tiers, because a binary scheme would lie in the one place that matters.** Traced
means an artefact and a digest over it. Attested means a named person's written word, which
is traceable to a name and a date but not to a document. Exempt means a convention or a
structural reference: **the gate agreed not to look at this number.** Defect means unbound.
Colouring a convention like a traced value would make the annotated copy actively
misleading, in the document whose whole purpose is to be trusted at a glance — and an author
who sees how much of their Methods is amber has learned something the pass/fail line cannot
tell them.

Two implementation notes, both about not repeating this repository's recurring mistake.

The annotation is emitted **during substitution**, where the pipeline already knows exactly
which key it is replacing, and from the same classifier the gate uses. Re-reading the built
document and inferring what each number was would be a second implementation of "what is
this number", which is precisely the drift several rounds of review have been spent
correcting elsewhere.

The first version of this shipped two defects that a passing test suite could not have
caught, both found by opening the file. **The highlight never reached the page**: it was a
custom character style wrapping a link, OOXML allows one `w:rStyle` per run, pandoc's Link
writer puts `Hyperlink` there, and the custom style was silently discarded — styles defined,
document valid, every number unmarked. And **the annotated copy had no tables and no
figures**, because it annotated the source and substituted only *value* bindings, so
`{{table.baseline}}` printed literally. An audit document missing the artefacts a stale
number is likeliest to survive in is worse than none. The colour is direct run formatting
now, ordered after `w:rStyle` because Word drops run properties it finds out of place, and
the tests assert on the bytes rather than on the style definitions — reading the XML for a
style definition is exactly what missed it.

**Two numbers that read the same never share a provenance.** Marks are built from offsets —
a binding's span from the placeholder parser, a literal's from the tokenizer — and never by
matching text, so two keys that happen to render `1` are two marks with two anchors and two
tooltips. In a paper full of 1s and 2s that is the common case rather than an edge one. The
same reasoning runs the other way: a literal that happens to equal a published value is
still coloured red, because in source a results-derived number may not be a literal at all.

And the tooltips are injected into the `.docx` afterwards, because **pandoc drops a link
title** on the way to Word — verified before the design depended on it, not assumed. They
are keyed on a per-occurrence anchor rather than on the visible text, because two numbers
that read the same must not share a provenance, and in a paper full of 1s and 2s that
happens immediately. The highlight itself is a character style injected into pandoc's own
reference document, generated at build time rather than committed: a reference `.docx` is a
binary, and this repository ignores `*.docx` precisely so a build product cannot be mistaken
for a source.

The annotated copy is deliberately **not stamped**. The source stamp is what G1 reads to
decide whether the document a co-author opens is current, and there must be exactly one such
document. This one is named so it cannot be mailed to a journal by accident, for the same
reason `manuscript.UNCHECKED.docx` is.

## Getting a number out of the red

`check` says a number is unbound and the annotated copy colours it red. Neither says what to
type next, and the four routes out are not equally likely: usually the value is already in
`results/` and the author typed it instead of binding it. `manuscript-guard bind` looks for
that case, and `--apply` makes the replacement.

**A value match is a suggestion, never evidence.** The gate refuses to accept a number
because it *matches* one — nothing may pass by coincidence, which is the whole reason a
results-derived number cannot be a literal at all. Offering a match as a fix is a different
act entirely: the author accepts it, the literal becomes a binding, and the binding is then
checked structurally like every other. The comparison decides what to *suggest* and never
what is true, which is why `bind` can use the value while G2 must not.

Where two published values read the same, the suggestion is refused rather than guessed. The
worked example makes the case concrete: `77` is both `results.case.n_cases` and
`results.table2x2.a`, so `bind` lists both and changes nothing. Quietly picking the first
would write the wrong binding into the manuscript, which is worse than leaving the number
red — and it is the same collision that makes a lone table cell weaker than a composed one.

Replacement is by offset, never by text. "Replace 1 with a binding" done by search-and-
replace would be a catastrophe in a paper full of 1s, and structural numbers — Table 8, item
8 — must be left exactly where they are.

## The round trip carries prose, and refuses everything else

"The document is a build artefact and never edited" is the right rule and, on its own,
unusable. Co-authors edit in Word — senior ones especially — and "please learn Markdown" is
not a thing anyone gets to say. So the round trip has to exist, and the only real question
is what it is allowed to carry.

Converting a built document back shows what is at stake. `{{results.ror.point}}` returns as
`3.84`, `[@fictionalClassSignal2019]` returns as "(Fictional and Fictional 2021)", and an
emitted table returns as ordinary text. A naive import would replace every binding with the
literal it currently renders to — turning a checked manuscript into an unchecked one that
still *passes*, because the literals match what the analysis said at that moment. It would
fail silently, months later, the first time the analysis changed. That is worse than having
no round trip at all.

So prose comes back and generated things do not. A hunk that removes or alters a published
value is refused and told what it was: "'3.84' comes from results.ror.point. Change the
analysis, not the document." Rewording *around* a number is fine, because the value survives
the edit; only a hunk that drops it is refused. Comments become findings to answer, since a
co-author's comment is the most valuable thing in the returned file.

Three things make it safe rather than clever. Both sides of the comparison are read the
same way: the document as it was sent is rebuilt from the source and read by the same parser
as the document that came back, so what remains is the edit and not pandoc's formatting
habits. A returned document must carry the digest of the source it was built from — stored
*inside* the `.docx` as a custom property, because a sidecar cannot survive being emailed —
and a mismatch is refused as a merge conflict rather than resolved. And a paragraph whose
identity the identifier cannot vouch for is left alone: splicing an edit into the wrong
paragraph is the failure this command must not have.

**A move needs no content from Word at all**, and that is the one thing the round trip can
do perfectly. Each source paragraph is tagged with an invisible identifier before
substitution — `[]{#mg-p-main-12}`, which pandoc emits as a Word bookmark: invisible,
surviving an edit, and travelling with the paragraph when somebody cuts and pastes it. When
the document comes back, the identifiers say exactly which paragraph is which, so a move is
a reordering of text already on disk rather than anything imported. That makes it safe for
precisely the paragraphs the content merge has to refuse: a paragraph solid with bindings
can be moved without a binding going anywhere near Word.

**Only a paragraph carries an identifier.** The marker first went in front of every block
that was not a heading, a fence or a lone placeholder, and in front of a list it stopped
being a list: pandoc read `[]{#mg-p-a-1}- item one` as a paragraph, so every bulleted and
numbered list in a manuscript reached Word as one run-on line with its dashes and numbers in
it, and a block quote became a paragraph opening with ">". Nothing reported it, because
nothing looked at the document. Line blocks, grid and multiline tables, rules, footnote
definitions and lone images (which stopped being figures) broke the same way. The marker
could instead have gone inside the first list item, where pandoc still parses the list —
and that was rejected, for the same reason a pipe table and a definition list are refused a
marker even though they survive one: the bookmark then sits in *one* Word paragraph (the
first item, the first cell, the term) while it names the *whole* source block, and `import`
splices the returned paragraph over the block it names. A co-author's edit to the first
item would have replaced the list with that item. That was not hypothetical: a paragraph
closing a fenced div without a blank line (`Inner paragraph.\n:::`), a list item's
continuation followed directly by a nested list or the next item, a paragraph with a LaTeX
environment opening on its second line, and a paragraph with display math in it were each
marked as one block, and `import --apply` deleted the `:::`, flattened the items into the
paragraph, deleted the environment's opening and first row, or deleted the equation and the
sentence after it — and exited 0. The last is invisible to pandoc's reader, which keeps
`$$...$$` inside the paragraph; its Word writer gives the equation a paragraph of its own and
the bookmark stays on the words before it. So a block is marked only when the whole of it
becomes one paragraph, and `tests/test_pandoc_agreement.py` asks pandoc directly, of both its
reader and the .docx it writes, for each construct in its table, whether that holds.

Four review rounds each found another structure a marker could slip inside, the last a
multiline table with its caption straight under it, where the marker became a bookmark on
one cell and `import --apply` deleted the rest of the row from the source. So `import`
also refuses the identity outright where it can never be right: a bookmark inside a table
cell is ignored when a document is read back. A cell is never a source block, every build
before this change put a bookmark in each pipe table's first cell, and a construct the
patterns miss could put one there again. Lists and quotes cost their identifiers, and their edits are counted as
unexamined rather than merged; see Known gaps.

Two details earned themselves. Only the paragraphs outside the stable backbone are reported,
because moving one paragraph shifts every paragraph after it and saying "fifteen moved" is
true and useless. And a move and a rewording are applied together. The identifier makes
them separate questions (where does this paragraph go, what does it now say), but both
answers are written to the same file, and the first version wrote them one after the other:
it reordered the file, then spliced each rewording in at the offset it had recorded *before*
the reorder. A co-author who moved one paragraph and reworded another produced
`{{lit.agency.withdrawnWhether the signal extends...`: a binding cut in half, a sentence
gone, the edit lost. (An earlier draft of this section said a moved paragraph was "excluded
from the content diff". Nothing excluded it; with identifiers nothing needs to.) The import
is now planned first, from one reading of each document, and written in one pass from one
snapshot of the offsets: every paragraph slot receives the paragraph that now belongs
there, reworded if it was.

The slots are counted per *section*, the stretch between two headings, tables or figures -
or, since lists and quotations stopped carrying identifiers, anything else without one - and
not per file. A heading is not a slot, so filling a file's slots in the returned order
let a paragraph moved from the Discussion to the Introduction push one paragraph out of
every section in between, each into the next, with "reordered 1 paragraph(s)" printed and
the tests comparing `sorted(...)` and seeing nothing. Import cannot change how many
paragraphs a section holds, so a move past a heading, table or figure is reported and
refused, like one into another file. What is out of place is found by keeping the largest
set of paragraphs whose sections read in order, with the headings as the document was sent
held fixed; the order diff only breaks ties. Judging only the paragraphs the diff called
moved missed a paragraph dragged to just below the next heading, which keeps its place among
the paragraphs, and blamed a neighbour when the diff preferred it. The file-level check
before that reported the single paragraph of a one-paragraph file as moved into another
file when nothing had moved at all.

Some paragraphs of source are more, or less, than the paragraph Word shows, and no move may
refill their slots. An HTML comment with a blank line in it is two paragraphs of source: the
first reaches Word as an empty line, the second does not reach it at all. Filled like any
other slot, the first half moved and the second stayed, and a paragraph dragged below the
empty line that ends the example's Methods was written inside the comment and vanished from
the next build. A `:::` or a code fence written directly under a paragraph belongs to that
paragraph's source but not to its Word text, so it travelled with the paragraph, and a
rewording deleted it: the div then ran to the end of the document. Five kinds of paragraph
are now held in place, each a section of its own, so a move past one is reported like a move
past a heading:

- one that never reaches Word;
- one that opens a comment it does not close, or whose raw markup runs on into the next;
- one that renders nothing;
- one with a line directly under it that opens or closes something else: a `:::` or code
  fence, an HTML block tag such as `</div>`, `\begin` or `\end`, a definition, or a heading's
  underline;
- one that Word shows as more than one paragraph: with untagged text before the next
  paragraph of its section, or with display maths in its source, which Word sets apart
  even when the paragraph ends its section.

None of them takes a rewording. A held paragraph the co-author drags past two paragraphs or
more, or past a heading, is reported by name, like any other paragraph that left its
section. The first version made it an anonymous anchor, so a held paragraph dragged past a
heading was dropped with "nothing came back"; the second weighed it above all other
paragraphs together, so dragged to the top of the Methods it had the four paragraphs it
passed reported instead. It now outweighs one paragraph and not two. Whether a paragraph
reaches Word in parts is still judged within the sections the source has. Judged within the
finer sections that holding creates, a one-line comment after a definition list hid the
split, and a rewording of the term deleted the definition. Whether a paragraph opens a
comment or holds display maths is read with its code spans and closed comments set aside,
so `$$` or `<!--` inside backticks holds nothing. Searched for as written, they held a
paragraph that explained them in inline code. The rewording's own scan of inline markup was
tried next and set aside too much: it took `` `glmer` from $$…$$ `nlme`{.r} `` for one code
span, and `~~ $$x$$ ~~` for struck-through text, so display maths went unseen and the first
part of such a paragraph was moved without its equation. Setting aside too little only
holds a paragraph that could have moved: `$$` inside a footnote does. A backtick escaped with
a backslash opens no code span; taken for one, it swallowed the `$$` or `<!--` up to the next
real code span. Escapes are read as pairs, so the backtick after an escaped backslash still
opens one: refused after any backslash, the closing backtick of `\\` then `` `data` ``
opened a false span of its own. Nor does a backtick just before an opener stop it. That
backtick is an escaped one, as in `` \``onset` ``, or one of a run that never closes, and
pandoc opens a span on a run's last backtick, as in ``` ``crude'' ratio came from `ror ```.
Stopped, the real span's closer was taken for an opener, and the false span it began hid
the `<!--` after it: a paragraph swapped in the Introduction was written inside the
comment, exit 0. Display maths is also read from the document as sent, which
says it outright: an equation directly after a paragraph is part of that paragraph, however
its source is written. And a held paragraph whose only change is a no-break space pandoc put
in and Word's editor took out again has nothing to merge, as an ordinary one has not; it was
refused instead. That is decided only for a source with no no-break space of its own and no
binding or citation: asked of every paragraph, the check dropped a co-author's change to one
the author had written, with "nothing came back". An author can write one as `\ `, as the
character, or as an entity pandoc reads, `&NonBreakingSpace;` and `&#0160;` included. It is
also decided only when no new text stands beside the paragraph. Only the part carrying the
identifier is compared, so when the part after an equation had been reworded, skipping the
paragraph dropped that rewording.

Headings and captions are matched between the two documents as a sequence, not one text at
a time. With two "Outcome" subheadings, matching by text alone, first come first served,
made the second stand in for the first once the first was renamed or deleted. The second
was then reported as having moved, and a real move in the same document went unnamed. A
text the sequence leaves exactly one copy of on each side is then paired too, which is how
a dragged heading is still found: paired only when its text was unique in the whole paper,
a dragged "Outcome" with another "Outcome" elsewhere was paired with nothing, and the drag
went unreported.

A table or a figure is a boundary only if it can be found again in the returned document.
They were matched by position, both kinds together, and only while their total was
unchanged, so a co-author who deleted one table or pasted in any picture switched every
boundary off, and a paragraph dragged below a figure came back as "nothing came back". Each
is now matched within its own kind by what it holds: a table by its text, a figure by the
bytes of its picture, because Word renumbers and renames the part a picture is stored in
every time it saves. What is left is paired by place, within the stretch between the same
two headings, captions or matched tables and figures, when that stretch holds as many of
the kind in both documents. Paired by position anywhere in the document, a table deleted
from the Results and another pasted into the Funding were taken for one table, and the
deletion went unreported. One that cannot be found is reported and makes the command exit
1, because a move past it cannot be seen. A heading, table or figure that is found but came
back somewhere else is reported too. It had been the anchor the ordering dropped, which
named nothing. A display equation is a block of the same kind, known by its text. Word
keeps it as OMML, whose text is not `w:t`, so it was read as an empty paragraph: dragged
into another section or deleted, it came back as "nothing came back".

**Rewording a paragraph that quotes a number now works too.** A source paragraph is prose
and protected tokens in alternation: bindings, and citations in the forms pandoc reads,
`[@key]`, `[see @key, p. 4]`, `[@key, p. 3 [emphasis added]]`, a narrative `@key` and `@key
[p. 33]`, with any key pandoc reads: `@2019who`, `@_key`, `@Élodie2020` and `@{10.1000/xyz}`
as well as `@smith2020`, and none straight after a full stop, where pandoc reads none. A
narrative key takes the bracket group after it, with or without a space and across a line
break, because pandoc reads `@key[p. 3]` as a key and its locator and `@a [see @b]` as one
citation; a group followed by `(` or `{` is a link or a span instead. A binding inside a
citation is part of it, and nothing in code, an autolink or a link's address is a citation.
Each of these was once split or found where pandoc finds none, and marking then broke the
paragraph for good. A key left in the prose all the same refuses the paragraph, since Word's
text holds the citation's rendering and not the key. Where each token's rendering begins and
ends is not worked out. It is read from a second build of the same source in which every
token has a Word bookmark around it, written as raw OpenXML that pandoc passes through. So
nothing about how a number or a citation renders has to be known, which is what makes
citations work: their rendering depends on a CSL style this code never sees. The first
marking was a `[token]{#id}` span, and a span adds brackets: beside an unbalanced one, as in
"Scores in [low, high) … [@key]", pandoc paired them differently, the text still read the
same, the extent lost its first character, and a rewording wrote the `[` twice. A bracketed
citation is found by bracket balance - a group with a key at its own level - and not by a
pattern: one that started at the first `[` made the prose "[low, high) were rescaled as in"
part of a citation, and one that could not contain `[` protected nothing in `[@key, p. 3
[emphasis added]]`.

It used to be worked out, and the working was wrong in both directions. The source's prose
was flattened and searched for in the rendered text, and the tokens were whatever lay
between. Pandoc typesets prose (`drug's` reaches Word as `drug’s`, `--` as a dash), so every
paragraph with a binding and an apostrophe was refused. And a short piece of prose could be
found inside a token: in "(Smith et al. 2020)." ending a paragraph the final "." was found
after "al", and a rewording merged as `[@smith2020]. 2020).`; in "(Smith and Jones 2020)
and (Lee 2021)" the " and " was found inside the first citation, so a co-author's edit to
the citation merged as prose. A narrative `@key` was not protected at all, and came back as
the plain text "Smith (2020)". The marked build costs a second run of pandoc per import.

Those rendered forms are then found in the returned text by aligning the two word by word,
with a number counting as one word. The first version searched for each as a substring,
from the start of the paragraph: '3.84' was found inside '13.84' and merged as
`1{{results.ror.point}}`, and in "Table 1 shows 1 events" the binding landed on the table
number. Now each token must come back whole, in order, inside a stretch of words the
co-author left alone. Any dash or mathematical symbol typed directly in front of a value
counts as changing it: a list of the four obvious signs missed the en dash Word's
AutoCorrect makes of a hyphen, and "–3.84" merged as a negative ratio. If one does not, the co-author changed a number or a citation, and the paragraph is refused
naming each one: "'3.84' comes from results.ror.point", as this section promised long
before the command did it. Otherwise the text between them is the new wording, and the
paragraph is rebuilt from the *source's* tokens and the *co-author's* words. Alignment is
monotonic, so a paragraph quoting two values that render the same string pairs them up in
order rather than matching both to the first occurrence — the same collision that `bind`
refuses to guess at.

Two details are load-bearing. Prose is only ever compared with rendered prose: a returned
segment with the same segment of the build, character for character but for layout
whitespace, since both are Word's text and Word changes no character nobody typed. Quotes
were once compared as quotes, and a co-author turning ‘em the right way round left a segment
that read as untouched: the correction was dropped with nothing reported. And an unchanged
segment is rebuilt from the source rather than from Word, so only a segment the co-author
actually edited loses its inline formatting — Word text is read as plain `<w:t>` runs, and
that is the price of using the bookmark as identity. An edited segment keeps Word's quotes
as they are: straightening them all for pandoc to curl again turned „ein Signal“ into
“ein Signal” and the ’90s into ‘90s. One is straightened. A straight `'` kept from the
source can open a quotation that closes in the edited segment, and pandoc, finding nothing
straight to close it, prints it as an apostrophe: "’a ratio of 3.84’". The read-back check
below compares quotes as quotes and cannot see that, so the segment's first closing `’` is
written straight, as the source had it.

Losing bold is a cost; losing a footnote is a corruption. Word's text holds nothing of an
HTML comment, a footnote, an equation or raw TeX; it holds a link's words without the
address, and `10^9^/L` as "109/L". Rebuilt from that text, a paragraph lost them, and only
footnotes and links were caught. The source is now read the way Word shows it, construct
by construct, and an edited stretch of prose that holds one of them refuses the paragraph
and names it: "the edited text carries an HTML comment and a footnote". A stretch the
co-author left alone is rebuilt from the source, so a footnote before a binding survives an
edit after it. Emphasis or code wrapped around a binding is refused the same way, because
each side holds a delimiter whose partner is on the other, and rebuilding one side left the
other unpaired, printed as literal asterisks. So is code holding what pandoc typesets in
prose, a `--`, a `...` or a quote: rebuilt from Word's text it was prose, and `--offline`
printed as "–offline" and `<!--` as "<!–". Escaping those characters would print Word's
text as it is, but a `--` a co-author typed with AutoCorrect off would then print as `--`
and not as the dash pandoc makes of it, which is what they meant. Other code merges as
text, and prints the same without its formatting, but for the no-break space pandoc puts
after an abbreviation it knows: `e.g. x` in code comes back with one after "e.g.". An edit
that deleted the code leaves nothing to typeset, and merges.

The paragraph is read whole, with each binding filled in as digits, because what a stretch
is depends on its neighbours: `*{{results.x}}*` is italics around a number, and
`US$5–US${{results.hi}}` is a price range, not an equation. Read one stretch at a time,
neither was either.

Word's text is literal, and the source is Markdown, so every character in what comes back
that Markdown could read as markup is escaped, its edges read with the binding or citation
that will stand beside them: `(see Table 2)` typed straight after a citation's `]` was a
link. `CYP2D6\*4` is shown in Word as `CYP2D6*4`; written back bare it opened italics, and a
co-author's `@admin` became a citation and a typed `{{results.x}}` a binding. A `(` straight
after any `]` is escaped, because the `]` may close a `[` of the source's own, in a stretch
kept as it was. A `{` typed before a binding is written `&lbrace;`: escaped as `\{`, it
joined the binding's own braces into `{{{results.x}}`, which `check` refuses as malformed,
and `&#123;` put a 123 into the prose for G2 to refuse. A `]` typed straight before a
binding or a citation is escaped too, whatever follows it: the build fills a value in as it
is, and one that opened with `(` became a link's address. Two other ways
were tried and beaten in review. Refusing every escape refused most of a paper converted
from Word by pandoc, which escapes by habit. Escaping only what this module's reading took
for markup trusted a reading that is close to pandoc's and not the same: `<LLOQ in mg/L and
>` is a tag to pandoc, was text to it, and the words were deleted at the next build.
Escaping never depends on that reading now. A backslash before punctuation does not change
what pandoc prints, except before a quote, a hyphen or a full stop, which it would stop
typesetting; those are escaped only where they open a paragraph as a list would (`1990.`,
`- `), and there nothing is typeset.

Then the rebuilt paragraph is read back the way Word should show it, and must read as what
the co-author wrote, or the merge is refused. That check uses the same reading, so it
catches what this module can see - a delimiter left unpaired, a span stretched over new
words - and not where the reading and pandoc disagree. Its tokens must be the source's, each
read as before and none touching the next. Counting them was not enough. An edit deleting a
space made `[@a][@b]` a link and `cohort.@key` no citation at all. One deleting "and " made
`@a [@b]` one citation, and one leaving `@a:{{results.x}}` gave pandoc the key `a:3.84`.
Each still had as many tokens, and the build printed a raw key or a garbled citation. The
reading takes a binding for digits, so what a value does beside a key is checked apart: a
value that opens with `[`, left after a narrative key with only spaces, a tab or one line
break between them, is the key's locator to pandoc, and "(2019) [pooled]" printed as "(2019,
pooled)". Only for a key without a locator of its own: pandoc takes one, so `@key [p. 3]
[pooled]` prints the value as it is, and a key that has its `]` is not read on into what
follows. A no-break space between them makes no locator either. The check was once broader
than pandoc on both counts, and refused edits that printed as Word showed them. Every edited
stretch has one more backstop, for what the list does not name: if its source, read as Word
should show it, is not what the build printed of that stretch, something in it never reached
Word as text, and the rewording is refused rather than rebuilt from what did. `[Methods]`, a
link to the heading, was rebuilt as the word "Methods", and `<LLOQ in mg/L and >`, a tag to
pandoc, was deleted. At first only a paragraph without bindings had this check. With
bindings, looking for the source's prose in the build did that work, and when marked extents
replaced that search the check went with it.

Two shapes of paragraph have no single Word paragraph to merge from. Display maths splits
one: pandoc renders "Before $$y = z$$ after." as three Word paragraphs, only the first
carrying the identifier, and a rewording of that first part replaced the whole source
paragraph with it. Such a paragraph is refused, recognised by the `$$` and, more generally,
by anything untagged standing between two paragraphs of one section in the document as
sent. A paragraph with display maths is no longer given an identifier at all, so its edits
are counted as unexamined; the refusal still guards a document built before that. And a paragraph that renders nothing - the example's HTML comment reaches Word as an
empty line - has nowhere to put text typed there: merged, it replaced the comment's first
half, and the second half built into the Methods. Text typed on such a line is refused.

A paragraph cut down to its number is still a paragraph. `tag` gave no identifier to
anything that was only a placeholder, because that is how a table or a figure is written,
and it did not ask which kind. A co-author who deleted everything but `3.84` merged as
`{{results.ror.point}}` alone, `check` passed, and the next build left that paragraph
without a bookmark: its next edit in Word was skipped with "nothing came back". Now only a
table, a figure, or a misspelt placeholder that `check` refuses goes without one when it
stands alone. A rewording that would leave nothing but one of those is refused and named,
because merged it would build with no identifier, and no later edit could come back to it.
A table cannot get that far in practice, since pandoc makes a table of the whole paragraph
it stands in; a misspelt placeholder in a document built with `--skip-checks` can.

**The identifier marks where a paragraph starts, not where it ends.** Word keeps a
paragraph's bookmark at its start, so a split leaves the first half carrying it and the
second half anonymous, and merging "the paragraph" replaced the whole source paragraph with
its first sentence. A join puts two identifiers in one paragraph, and the first used to
absorb the second while the second was reported deleted and left in place, so its text was
in the source twice. Neither is guessed at now. A tagged paragraph touching text the sent
document did not have may have been split, and a rewording of it is refused; a paragraph
carrying two identifiers, or one that took in a run of a vanished neighbour's words (a join
made by selecting across the boundary deletes the second bookmark), is reported as a join
and nothing in it is applied.

The returned document is parsed, not searched. `<w:t[^>]*>` also matches `<w:tab/>`,
`<w:tabs>` and `<w:textAlignment/>`, and the lazy match then ran on to the next `</w:t>`: a
paragraph with a tab in it merged `</w:r><w:r><w:t xml:space="preserve">` into the source.
A paragraph's text is its `w:t` elements read with every tracked change accepted, so a
paragraph deleted with Track Changes on is reported as deleted. It used to come back empty
and be refused as "a number or a citation changed".

## An exemption has to prove itself

The recurring defect of this project is not a wrong regex. It is an escape hatch whose first
version *believed its own claim*.

`composed` exempted a table cell without checking that the exemption described it, so an
entry declaring an empty template exempted whatever the cell actually said. `Verbatim`'s
docstring asserted that a script could not build one; it was an ordinary importable
dataclass. `file_sha256` scoping was a way to review one file and pass until
`review-uncovered` was invented alongside it. Composed `parts` were folded into one
project-wide allowlist, so a phantom entry in a table with no rows whitelisted its strings
in a different fragment. Every one of those was found by a reviewer or by opening a file,
never by a test — because nothing required an exemption to be self-verifying.

`tests/data/exemptions.yaml` lists every place the toolkit agrees not to look, what each one
stops checking, and the test that claims it falsely and expects to be caught. The build
fails if an entry has no such test, if the test it names does not exist, or if that test
does not pass. It is the countermeasure `rule_cases.yaml` already applies to classifier
rules, raised to the whole toolkit.

The check runs in both directions, and the second is the one that rots: a list that only
grows when somebody remembers to add to it is the same "not checked looks like checked" this
repository keeps finding. So each exemption's spelling is looked for in the source — grant
one in code and leave it off the list, and the build says so. It earned its place on its
first run, by finding that the code-list exemption had no abuse test at all.

## Assert on the artefact, not on what should have produced it

Two defects shipped in the annotated copy because the tests checked an intermediate. The
highlight never reached the page — the test asserted that the character styles existed in
`styles.xml`, which stayed true while OOXML discarded them, since a run carries one
`w:rStyle` and pandoc's Link writer had already taken it. And the copy contained no tables,
because only *value* bindings were substituted. Neither failed anything; both were found by
opening the document.

`tests/test_artifact.py` unzips what was built and asserts what a reader would see: the
highlights are present and coloured, the tables and the figure are there, no placeholder
survived to the page, the source digest and the paragraph identifiers travel inside the
file. Slower than testing the code that was supposed to do it, and the only kind of test
that would have caught either.

And `example/` is checked against the public API, because the example is the spec — every
new user copies it. `code_list()` existed for a day with nothing in `example/` using it: the
one API added to make a reporting requirement satisfiable, absent from the artefact that
demonstrates the toolkit.

## The response to the reviewers is a document full of unchecked claims

Every other gate checks the manuscript. G13 checks the letter that goes with it.

A point-by-point response is made almost entirely of statements about the paper: "we have
revised the Methods", "the analysis has been rerun", "Table 2 now reports the counts". Each
is a claim nobody verifies. The journal cannot see the diff, and the authors wrote it from
memory at the end of a long revision. **The commonest failure is not dishonesty — it is a
response written before the change, and the change then made differently, or not at all.**

So a revision round records the manuscript as the journal received it, one digest per file,
and each response names what changed because of it. A claim that a file was revised is
checked against whether that file differs from what went out; a claim about a results key,
against whether the key exists. A point with neither a change nor a recorded rebuttal is
unanswered — "Done." names nothing and can be checked against nothing.

When the points come from a document this tool built, the anchor comes with them. A Word
comment records which paragraph it marks, and paired with the invisible paragraph
identifiers that turns "reviewer 2 said something about the Methods" into a point that knows
where it applies — so the round also stores a per-paragraph baseline, and a response claiming
a revision can be asked the tighter question. A file differing is satisfied by any change
anywhere in it, and a paper's Methods is one file.

The baseline is the whole mechanism, which is why `respond --open` says so: open the round
before revising, or there is nothing to compare with.

**A reasoned rebuttal is a complete answer.** Disagreeing with a reviewer is often the right
thing to do and is not the same as ignoring them — the same bargain as `overridden` on an
internal finding. What is enforced is that the reason exists and is not blank, and the
response document prints it in the author's own words rather than inventing agreement.

Severity follows the internal panel: an author part-way through a revision must still be
able to build something to read, so ordinary work warns and a resubmission fails.

## Round five, and what it says about the last two days

Four reviewers, all able to run their reproductions this time. The revision cycle and the
Word round trip had had no external review at all, and the result is the clearest instance
yet of this project`s recurring defect:

**Two of the six findings were functions whose docstrings promised a comparison the body
never made.** `_anchor_unchanged` read the recorded paragraph digest into a variable and
then checked only that the identifier still resolved - so a response could claim a revision,
change something else in the same file, and the paragraph the reviewer actually objected to
went untouched with the gate silent. `_unverified` compared `submitted.get(name)` against the
current digest, and `.get` returns None for an absent key, which is never equal to a digest,
so a claimed revision of any file the baseline did not happen to list fell through to
"verified". Both were written the day before, both by the author of this paragraph, and both
read correctly right up until somebody executed them.

**A third was a lesson learned in one file and not carried to another.** `file_digests` was
fixed in round four to key on the path relative to `manuscript/` rather than the filename,
because `source_files` walks subdirectories and two files called `notes.md` collapse into
one entry. The paragraph identifiers introduced a day later made exactly the same mistake,
and the consequence was worse: the built document carried the same bookmark twice, and a
co-author`s edit to one of those paragraphs was neither merged nor refused. It vanished, with
`import --apply` exiting 0 and printing "nothing came back".

The other three: a path join that accepted `C:/Windows/win.ini` as evidence a figure was
updated, a cross-file paragraph move that the docstring promised to refuse and instead
applied to the wrong file, and two spellings of one reviewer`s name becoming two headings
in the letter that goes to the journal.

The pattern is stable enough to name. **Every one of these is a claim that outran its code**,
and the countermeasure that works is the one already in the repository: a test that executes
the claim. `tests/test_round_five.py` holds one per finding.

## The round trip, edited the way Word edits

A read-only review built the example, edited `word/document.xml` the way Word does (a move
and a rewording together, a split, a join, a tab, a tracked deletion, a digit added to a
number) and imported each. Every one either damaged the Markdown source or misreported what
happened, and most exited 0. The source of truth was being rewritten by the command whose
whole purpose is to protect it.

The tests had only ever edited text *inside* a paragraph, one edit per document. Every
failure was at a boundary those tests never crossed: between two operations applied to one
file (offsets taken before a reorder, used after it), between paragraphs (a split, a join),
between a regex and the XML it was guessing at (`<w:t[^>]*>` matching `<w:tab/>`), between
a value and the digit next to it (`3.84` found in `13.84`). And one was the recurring defect
in its purest form: DESIGN.md and the module docstring promised a refusal naming the value
and its key, and the test named `..._refused_and_named` checked only the exit code.

Two findings were not in the importer. The broken placeholder it wrote passed `check`,
because the loose pattern needed a closing brace to call anything a placeholder; it now
needs only the namespace-and-key shape. And the document sent to co-authors carried the
builder's home directory twice: the bibliography's path as a document property, and the
figure's as the picture's description. Pandoc now runs from the project root with
relative paths. `tests/test_roundtrip.py` holds each case as a document edited the way Word
would edit it.

## Round six: running the commands, 2026-09-24

Eleven defects, each found by running a command on a copy of `example/` and reading what came
back, and a twelfth from a review of the same code. Round five's pattern again, in four
shapes.

**A claim that outran its code.** `normalise_number` promised "no sign noise" while the
pattern that read the outputs had no sign at all: -0.51 went into the backing set as 0.51,
so a paper quoting it correctly, with a hyphen or U+2212, was reported as not found, and a
paper printing 0.51 for it was reported as found. The second half is the one that matters,
and it is in the corruption harness. `split_sections` promised that "subsections stay inside
their parent's body" and ended every body at the next heading of any level, so G12 called a
Population written under `### Inclusion` a heading with nothing under it. Two more callers
had the same defect: G9 reported software named under `## Statistical analysis` as absent
from the Methods, and a structured abstract written with `##` headings had its words counted
as main text, where the abstract's limit could not see them. This file said the bibliography
was recognised "by entry shape"; the only shape was author-year, so every numbered style
was missed, and so was a heading reading "Reference list". The `--against` help named four
formats and the code read seven.

**A check that could not look, reported as a check that looked.** A reference heading cut
everything after it: an appendix after the references was never audited, and neither were
a .docx's footnotes and endnotes, which are read after the body. The author-year entry shape
was a capitalised word, a comma, another capitalised word and a year within 200 characters,
and in a .docx a line is a paragraph, so "Overall, Japanese patients accounted for 412 of
8,393 cases between 2010 and 2019." was a reference entry and none of its numbers was
compared with anything (found by a separate review). Each entry shape now has to carry the
year the way an entry does, "(2019)." or ". 2021." or "2019;393:100", with nothing but names
before an author-year one, and neither is consulted at all in a file whose reference list
was found by its heading. Four review rounds of this change each still found a caption some
shape accepted, and a caption can always be written to fit a shape. So a shape no longer
decides anything by itself: a line it accepts is compared like any other, and what matches
nothing is listed apart from the findings, in a section of its own. An SVG with its
labels drawn as outlines was listed among the audited files, with nothing unmatched in it. A path
in `--against` that did not exist, or a format the audit does not read, vanished; a typo
gave "0 output file(s)", every number in the paper reported missing, and exit 0. A .json
written with a byte-order mark, as Windows PowerShell 5.1 writes UTF-8, failed to parse and
was dropped the same way. Worse, an output in UTF-16, which PowerShell 5 writes for `>`, was
read as UTF-8 with a NUL after every character, so "8393,3.84" went into the backing set as
8, 3, 9 and 4, and a paper printing 3 for anything matched. A byte-order mark now names the
encoding, and NUL bytes without one are refused rather than guessed at (both found by a
review of the plugin that ships the audit skill).

The first fix for the sign was reviewed before it landed, and read "50%-60%" as 50 and -60:
it said where a minus could not be a sign, and a percent sign was not on the list. It now
says where a minus can be one.

**Advice that failed when followed.** `init` and two hints said to call `emit()`, which
exists in neither language. `bind` suggested `--only main.md:12` for a selector that has to
be `manuscript/main.md:12`, so the one command it printed exited 2. `respond --open --from`
refused an unstamped document and said `--force` would help; `--force` was refused too.

**The design gate failing at the one thing it does.** G12 warns and never blocks, by
decision. A plan saved in Windows-1252 made it raise, and a gate that raises is
`gate-errored`, which fails at every stage. And `# Analysis plan`, the title `init` writes,
satisfied the "analysis" requirement, so the empty `## Analysis` scaffolded beneath it was
never reported.

The reference list now ends at the next heading, which a .docx gives only in paragraph
styles, read by style name because a French Word's heading style id is `Titre1`. Notes are
read after the cut rather than through it, and the report names the lines it did not audit,
so a cut in the wrong place shows.

## Known gaps

Recorded because a gate whose limits are undocumented gets trusted beyond them.

- **One pandoc version is tested.** CI pins one, in `.github/workflows/ci.yml`: the version
  the tests that assert on pandoc's output were written against. It refuses to run the
  suite with any other. An author's pandoc may be older or newer, and nothing here checks
  that the build and the import behave the same with it.
- **Digests are byte-level, so line endings are part of the guarantee.** `.gitattributes`
  pins `eol=lf` here, and `init` now writes the same file into every scaffolded project:
  without it Git stores LF and hands Windows CRLF, and every byte-level check reports a
  change nobody made. A *script's* digest is normalised in code as well (`source_digest`,
  mirrored by `mg_source_digest` in the R emitter), so G1 stays right on a repository that
  predates the scaffold or was not made by `init`. A *fragment's* digest is still byte-exact
  on purpose: it must be reproducible from any language that can emit results, and "hash the
  bytes you just wrote" is the only operation meaning the same thing everywhere. So a project
  that deletes its `.gitattributes` can still see `results-edited` on a clean checkout. Found
  by dogfooding — the same omission in the author's own paper repository, `.csv` missing from
  a normalisation set, reported 16 stale outputs including all seven figures, every one of
  which re-rendered pixel-identical.
- **A fenced block tagged with a language the lexer does not know is not read.** Only
  Python and R have lexers, so a ```stata or ```sql listing is reported as unread rather
  than checked. Saying so is the point; it is still a hole an author could tag their way
  into.
- **`verify` cannot hide from the code it runs.** The easy tells are gone — no
  `MANUSCRIPT_GUARD_VERIFY`, no `manuscript-guard-verify-` in the scratch path, and no
  `PYTHONDONTWRITEBYTECODE`, which was set for tidiness and was the same backdoor in
  miniature: readable by the script being checked, absent in an ordinary run, so two lines
  make an analysis honest under verification and dishonest everywhere else. A script can
  still notice it is running under the system temp directory. An analysis written to deceive
  its own toolkit defeats this; an author who edited a results file does not.
- **`verify` runs untrusted code, so its own machinery is part of the attack surface.** The
  child gets its own process group and the whole tree is killed on timeout — an analysis is
  usually a launcher, and killing the direct child left a grandchild holding the scratch
  directory open. Its output goes to files and is capped, because with pipes the reader was
  this process and a grandchild holding one open outlasted the timeout meant to enforce it.
  Directory junctions are skipped explicitly when staging the copy: `symlinks=True` stops a
  symlink loop but `os.path.islink` is False for a junction, so `copytree` walked into one
  and re-copied the tree at every level, reachable by any unprivileged `mklink /J`.
- **A figure render manifest is a drift detector, not a proof.** `<name>.render.json` sits
  beside the figures it vouches for and is writable by whoever holds the checkout: retouch
  the raster *and* rewrite its digest and G3 skips it again, exactly as a `.sha256` can be
  recomputed. It catches the ordinary case — a raster re-rendered on its own and left beside
  a fresh vector — which is how the wrong figure actually reaches a journal. There is no
  `verify` equivalent for figures, because re-rendering is not reproducible across
  plotting-library versions.
- **The other rendered keys in a manuscript's front matter are read by G2 and printed by
  nothing.** `subtitle`, `summary`, `keywords`, `short_title` and `running_title` are read
  because pandoc can print them, and the build strips the block and takes its header from
  `paper.yaml`. A number in one is checked and never printed, which is the safe direction,
  but the text itself is dropped without a word. Only the abstract is refused
  (`front-matter-abstract`), and only the title is compared with `paper.yaml`
  (`two-titles`).
- **A front matter is composed twice, at 15 to 20 seconds a megabyte each time.** PyYAML's
  pure-Python composer is linear but slow: once to decide the block is front matter, once
  to look for an abstract in it, each cached for the rest of the process. With half a
  megabyte of front matter, which only a deliberately hostile manuscript has, `check` on
  the example took 30 seconds against the 20-second budget of `test_robustness.py`, and
  24 without the second reading. The C composer is 40 times faster and overflows its stack
  on deep nesting, which is why the pure-Python one is used.
- **A YAML block later in a file is read as prose.** Pandoc takes any `---` block that
  follows a blank line and holds a YAML mapping for metadata, wherever it sits, and prints
  none of it. The gates recognise only the block that opens a file, so a later one is read:
  its words count, and its closing `---` underlines the line above it into a heading. A
  block of `note: |` over an indented `Methods`, placed under `## Results`, gives G2 a
  Methods heading the document never prints, and `p < 0.001` after it passes as the alpha
  chosen in advance.
- **G4 reads the main-text files in path order, and the build prints them in another.** The
  build puts `main.md` first and sorts the rest by file name, not by path. A section's words
  count where the headings above it put them, so an `abstract.md` beside a `main.md` written
  in `##` headings makes the whole paper abstract as far as G4 can tell. The order also
  decides which comments and fences reach across files: an unclosed `<!--` or fence at the
  end of a file G4 reads first hides the next file's headings and statements up to the next
  `-->` or fence, where the build, reading `main.md` first, may print them. A project with
  one main-text file, which is what `init` writes, is unaffected.
- **G4's blanking of comments and fences is close to pandoc's reading, not the same.** A
  stray fence line inside a comment, or a fence directly under prose that is tilde or
  indented a space or more, hides what follows from the statement and abstract-heading
  searches while pandoc prints it, so a statement there is reported missing: a false alarm.
  A raw block, ```` ```{=openxml} ````, is blanked although pandoc passes its text into the
  document. An indented code block is not blanked, so a pattern written for a phrase can be
  met by a line of code; one anchored on a heading cannot.

Added by the adversarial review, verified and **not** fixed:

- **Re-signing still defeats G1**, and always will: the digest and the file it protects are
  both writable by whoever holds the checkout. What changed is that G1 is no longer the only
  answer. `manuscript-guard verify` re-runs the analysis into a scratch copy and compares
  the fragments value by value, and a result cannot be forged into existence the way a
  digest can be recomputed. It is a separate command because it executes the project's own
  code, which a gate must never do. It cannot make a non-deterministic analysis agree with
  itself; it reports the disagreement and says to set a seed.
- **Numbers written as words escape the tokeniser.** "four thousand and twenty-one" is not
  read. Vulgar fractions and enclosed digits now are. Number words are left alone on
  purpose: "one of the two arms", "a single centre" and "two-tailed" are ordinary prose, and
  a rule that flags them is a rule that gets the gate switched off.
- **`conventions:` and `terms:` in `paper.yaml` are self-service.** A pattern of `\d+` with a
  `why` of "house style" disables G2, and `terms:` needs no justification at all. The gate
  is a tool for an author who wants it, not a control over one who does not — so this stays.
  What has changed is that it is no longer *invisible*: every run reports how many numbers
  the project's own rules accounted for, and which rules did it, as `project-exemption`
  (a warning past a quarter of the numbers in the manuscript). Self-service and silent are
  different things, and only the first was intended.
- **`stage:` is declared, not detected.** Writing `stage: analysis` demotes every G2 finding
  to INFO. It is printed, counted and summarised — never hidden — but CI reading the exit
  code sees green.
- **G3 checks a number drawn in a figure for set membership, not identity.** A text node in
  an SVG is accepted if it equals *any* results display, not the one that belongs at that
  position — so a forest plot labelled with the right value against the wrong outcome passes.
  The gate cannot know which value a given text node is meant to be; nothing in the artefact
  says. The real protection is one level up: `figure-script-ignores-results` requires the
  script to read the results file, and a figure whose labels are drawn from results cannot
  carry another outcome's number. Set membership is the backstop for the figure nobody
  scripted, and should be read as "no number here is a stranger", not as "every number here
  is the right one".
- **The source-of-truth invariant does not survive a co-author round in Word, and a real
  paper is the proof.** This toolkit rests on "Markdown is the permanent source of truth and
  the .docx is a disposable build artifact". Run against a submitted pharmacology paper, the
  main text turned out to be a `.docx`: the project began markdown-first, twelve rounds of
  tracked changes happened in Word between May and July, none were back-ported, and the
  markdown was eventually deleted as the losing copy. The supplements, which never went
  through Word, are still markdown and still built from the pipeline.

  So the invariant held exactly where the review loop did not touch it. `import` and the
  paragraph round trip exist to prevent this and were built after the fact; whether they
  actually hold a manuscript together through a real co-author round is untested, because no
  paper has yet been through one with them in place. Until then, `audit` — the weaker
  question, asked of a document nobody bound — is not a fallback for awkward cases. It is the
  command that meets the situation a real paper is most likely to be in.
- **`import` compares only paragraphs that carry an identifier.** Table cells, headings,
  captions, list items, block quotes, definitions (the term of a loose definition list is
  one paragraph and keeps its identifier), footnote text, code, and anything the co-author
  newly wrote carry none. Those edits are not merged and not refused. Outside tables they
  are listed - reworded, deleted or reordered - and import exits 1; inside a table only the
  count of what went unexamined is printed, which is a report rather than a fix. A number
  corrected in a table is the case that matters, because that is where a stale number is
  likeliest to be. A document built before identifiers moved off lists and quotations comes
  back listing them as changed even untouched: the fresh build it is compared with sets
  them out as lists and quotations, where it had run them into paragraphs. Nothing is
  applied, and a current build sent out ends it. Lists and quotes are on the list by choice: a
  marker in front of one rewrote it, and a marker inside its first item would let `import`
  splice that item over the whole block (see "The round trip carries prose"). Comparing
  them needs an identifier per item and a merge that puts the list marker back, and neither
  exists.
- **Which blocks are paragraphs is decided by pattern, not by pandoc.** `tag` runs where
  pandoc may be absent, so it reproduces pandoc's rules — two spaces after "C." before it is
  a list, the inline HTML tags a paragraph may open with, what can interrupt a paragraph —
  and is checked against pandoc in `tests/test_pandoc_agreement.py`, which CI skips because
  CI has no pandoc. Where the patterns are unsure they leave a block unmarked, which costs a
  comparison and corrupts nothing. Known cases: a paragraph opening with an unrecognised HTML
  tag or a TeX command (`\noindent`), one holding a line of nothing but dashes and pipes,
  one starting "p. 12" (pandoc's abbreviation rule, not reproduced), and every paragraph
  after a `<!--` written inside inline code, up to the next `-->`; a paragraph whose braces
  do not pair. Raw TeX other than an environment is not followed across a blank line. When
  the blank line falls inside braces, the blocks either side are refused by the brace
  count, since `\footnote{One.\n\nTwo.}` is one paragraph to pandoc; a block wholly inside
  such a group, the middle of a `\newcommand` with two blank lines in its body, gets a
  marker, and pandoc drops raw TeX from the .docx so the identifier names nothing, which
  `import` already tolerates. When it falls inside an optional argument,
  `\cite[p.~5\n\nmore]{key}`, the braces pair on each side and both halves are marked:
  pandoc then prints the halves as literal text. The document shows it and `import` stays
  consistent with it, and counting brackets instead would refuse every paragraph quoting an
  interval such as `[0, 1)`. Every review round on these patterns found holes in the
  version before it,
  each by running pandoc on a construct the table did not yet hold, so the table is
  evidence for what is in it and no more.
- **A line pandoc does not call blank still ends a block for the numbering.** A line
  holding only a non-breaking space, an em or ideographic space or a form feed ends a block
  for the identifiers' numbering, while pandoc reads one paragraph across it. Marked, the
  first half's bookmark sat on the joined paragraph and `import --apply` wrote the second
  half twice; both halves are now left unmarked and never compared. Renumbering would fix
  it and would move every identifier after them. Over two stacked lines of dashes, such a
  line is a setext heading to pandoc and the second line opens a table; the table rules
  lose the line, take the heading's underline for the opener, and a paragraph inside the
  table can be marked.
- **A YAML block in the body is followed only where a block starts with it.** Pandoc tries
  every `---` in column 0 with text straight under it as YAML, up to the first `---` or
  `...` in column 0, and a marker at the start of a line inside turns its quiet fallback (to
  a rule, a table or prose) into a parse error that fails the build. So everything it tries
  is left unmarked, mapping or not. Two cases are not followed, and neither corrupts the
  source. A `---` that opens mid-block, straight after a code fence, straight under a
  table's closing rule or inside a fenced div with no blank line before it, fails the build
  when its YAML holds a blank line. An attempt that opens in one source file
  and stops in the next - each file is tagged on its own and the build joins them - builds,
  with the second file's paragraphs read into a table whose bookmarks `import` ignores, so
  their edits go uncompared.
- **A block that opens on a line of dashes is taken for a table whatever surrounds it.**
  When the line has text straight under it, `tag` leaves everything up to the table's
  closing line of dashes unmarked; with a blank line under it, the line is a rule and opens
  nothing. Pandoc reads no table there when the line continues a list item, sits inside a
  fenced div after a blank line, or follows a no-break-space line inside a paragraph. The
  paragraphs in between then go uncompared although pandoc reads them as paragraphs, and
  nothing is corrupted. Lines of three dashes or more had these cases already; since two
  dashes can open a table, `--` has them too.
- **A table that opens mid-block is followed only under the lines it was seen to open
  under.** Pandoc 3.9 opens one straight under a code or div fence, a whole line of
  block-level HTML, a setext underline, a grid table's border, a pipe-table row, a line
  opening on `|`, `\end{...}`, a comment's closing `-->` or a YAML stop, and under a
  heading or a one-line comment when the dashes hold two runs or more; `tag` follows it
  from there. Under prose, a list item, a quote, a definition, a caption, a TeX command, an
  image or a one-line reference definition it opens none: over a line of dashes, most of
  those are a simple table's header. A line of any other kind is taken to open none, among
  them a reference definition whose title continues on the next line, a line block's
  continuation and an HTML tag split over two lines. A table pandoc does open under one
  gets a marker in its rows, visible in the document; `import` then reports that paragraph
  as deleted in Word and leaves the source alone. The other way round costs only
  comparisons. A line taken for one of these that pandoc does not end a block under, over
  a line of dashes with text under it, hides the paragraphs down to the next line of
  dashes. Such lines sit inside code, a comment or a table's rows, or in prose such as
  `A -->`, `\end{x}`, `...` or a line opening on `|`. The block where that span ends is
  read again as any block is - below its first line when it starts inside code, since
  that line is code - so a real table the span runs into is still followed. Read only for tables opening further
  down it, the block missed a real table's own top rule, and the table's rows were marked.
  Four layouts are still not covered, all contrived. A span that ends on the underline of
  a header split by a blank line leaves the table's rows marked. A span that ends on a line
  of dashes inside a YAML block scalar leaves a marker in the YAML, and the build fails. A
  real table that pandoc ends on a line of dashes inside a code block pairs every later
  fence differently from `tag`, so a paragraph after it can be marked inside code; that
  one is older than this reading. And a block a span hides is not read for raw content, so
  a comment or an environment opened in a paragraph the span hides, and closed after the
  span, goes unfollowed: a paragraph inside it is marked, and the identifier names nothing
  in the document.
- **Code fences are paired by `text/fences.py`, not by pandoc.** Where the two pair them
  differently, a paragraph can be marked inside code, and the marker prints there. Known
  cases: an opener whose info string pandoc rejects (`python title="x"`,
  `{code-cell} ipython3`), a `~~~` straight under a paragraph line, since pandoc lets only a
  backtick fence interrupt a paragraph, and a fence line with no partner inside an HTML
  comment. The same pairing decides which blocks start inside code, so a table under such a
  fence can go unfollowed as well.
- **A heading with its first paragraph directly under it is one block, left unmarked.**
  `# Methods\nWe did X.` is a heading and a paragraph to pandoc, and since the block starts
  with `#` the paragraph never carries an identifier and its edits are never compared.
  Marking it would mean placing the identifier after the heading line. This was already so
  before identifiers moved off lists.
- **A review point anchored to a list or a quote before identifiers moved off them names
  nothing.** A `where:` recorded from a document built earlier can hold the identifier the
  flattened list carried. That block is no longer tagged, so G13 reports the paragraph as no
  longer in the manuscript rather than checking the response against it.

Closed since, and why each mattered:

- **Front matter closed by `...` took the body with it.** YAML, and pandoc, close a header
  with `...` as well as `---`, and the build's pattern took only `---`. It ran on to the
  next `---` line in the file, a horizontal rule, and the Introduction above the rule
  vanished from the document, from `import` and from G13, with no warning. The build now
  uses the pattern the gates use, which closes on the first `---` or `...` line, the file's
  last line included, and the line straight after the opening, where an empty header had
  run on to the next rule the same way. And it counts a block as front matter only where pandoc keeps it as
  metadata: a mapping, or nothing. A list or a sentence between two delimiters prints, so
  it is no longer stripped or masked. A header never closed before a later rule, with prose
  in it, is not YAML, and pandoc refuses the file. The build had stripped it into one that
  built without the Introduction. Now G2 and the build stop on it and name the YAML's
  error, as they do for any header pandoc cannot read. Leaving such a header in the body for
  pandoc to refuse was not enough: the identifier in front of its first paragraph made it
  prose, so the build printed the YAML as text, and a `# Methods` in it let `p < 0.001`
  pass G2 as the alpha chosen in advance. A header behind a byte-order mark or a blank first
  line is found too, as pandoc finds it, and tabs are expanded before the YAML is read, as
  pandoc expands them. Left in the body, such a header's title never met the two-titles
  warning, and G2 read its keys as prose.
- **A token straight after inline code stopped `import` for the whole manuscript.** The
  bookmark around a binding or citation is raw inline code, and against a code span's
  closing backtick its own backtick joined that run. Pandoc read the code and the bookmark
  as one raw span and wrote the code into the marked build as XML: `` `age<65`{{x}} `` made
  that build unreadable, and `import` exited 2 over a file the author had never seen. An
  empty comment now keeps the two apart, which the Word writer drops, so the paragraph
  still takes a rewording. And a marked build that cannot be read no longer stops the run.
- **G8 went quiet exactly when two keys had diverged.** It fires when two quoted keys hold
  the same value with different displays, so a duplicate was caught while it still agreed
  and missed once it did not — a paper could carry `ror.point` at 0.95 and `ror.abstract`
  at 3.84 and nothing said a word. `same_as` records the author's intent, and G8 fails when
  a declared pair disagrees. A declaration rather than an inference, because the question
  *is* about intent: `ror.point`, `ror.ci_low` and `ror.ci_high` share everything a
  heuristic could see and are supposed to differ. The limit is honest — it protects the
  pairs someone thought to declare — but a declared pair cannot drift in silence.
- **`p < 0.05` was a convention everywhere.** The same characters mean two things: where a
  paper describes its own method it is the alpha chosen in advance, and in the Results it is
  a finding. A significance claim the analysis never produced therefore passed the gate that
  carries the invariant. A rule can now be marked `methods_only`, and G2 reads the chain of
  headings enclosing each number — a chain rather than the nearest heading, because
  `### Sensitivity analyses` under `## Methods` is still Methods. Only G2 passes a section:
  a figure legend has no Methods section to sit in and its `p < 0.05` is a legend
  convention, so figure text and the audit keep every rule. One entailment: a display may
  now carry a comparator, since a reported p-value has to be emittable and "<0.001" is the
  honest rendering of a number too small to state. The value must be on the stated side of
  it — `display="<0.001"` on a value of 0.4 is refused.
- **`build --skip-checks` left a document that could pass for a checked one.** Revert the
  source afterwards and `check` passes while the stale `.docx` still holds the wrong
  number — the check and the artefact disagreeing silently, with nothing on disk recording
  which was skipped. An unchecked build is now written as `manuscript.UNCHECKED.docx`, and
  a submission pack assembled with `--skip-checks` says so in its own `MANIFEST.yaml`,
  which is the file whose entire purpose is to be the thing you can tell from.
- **Sidecar exemptions took a value with no reason.** `why` was optional in the code and
  mandatory in every message these gates print, so `- value: '1'` on its own exempted a
  number with no argument recorded anywhere. An entry without a reason is now ignored
  rather than honoured: an exemption nobody justified is one nobody can review.
- **`{{results.x}` was neither a binding nor malformed.** The loose pattern required `}}`,
  so a single missing brace travelled into the built document as literal text, in the place
  where a number was supposed to be. One typo, worst available outcome.
- **A `.jl` figure script produced an empty report**, which reads as "checked and clean".
  The lexer has no Julia entry; it now says the source was not read.
- **A point estimate outside its own confidence interval passed `check`.** `interval()`
  refuses it, and `interval()` was the only thing that did — the results fragment is a
  contract with three other writers (`value(bounds=…)` called directly, the R emitter, a
  hand-edited file), and none of them went through that helper. It is the one arithmetic
  error a reader catches by eye in the first sentence of the Results. Bracketing is now
  checked where every producer meets: at the fragment, by G2, along with an inverted interval,
  a bound of an estimate nobody published, and two bounds claiming the same end.
- **The reversed-interval check was disabled by restating a bound, and invented reversals
  that were not there.** The guard meant to keep the *first* mention of each end tested
  `value.bound in seen` while the keys were `"{bounds}:{bound}"`, so it never matched: the
  last mention won. "2.10 to 7.02, and a lower bound of 2.10 excludes unity" was reported as
  reversed, and a genuinely reversed interval that named its upper bound again went
  unreported. A false positive on ordinary writing is the worse half — an author whose only
  recourse is to delete a true sentence learns to distrust the gate.
- **One estimate could carry only one interval.** A 90% CI beside the 95%, or a credibility
  interval beside a frequentist one, is ordinary in a disproportionality paper and was
  inexpressible: `interval()` wrote one fixed pair of key names, and declaring a second pair
  by hand became a duplicated bound the moment bracketing started being checked — so closing
  that hole closed a door too. A bound now carries a `level`, `interval()` takes one and
  derives the key from it (`"90%"` → `ror.ci90_low`), and omitting `point` reuses the estimate
  rather than publishing it twice: two keys holding one number is what `same_as` is for and
  what G8 watches. Bounds are compared within a level and never across, because a 90% interval
  nested inside a 95% one is correct rather than a contradiction — in the fragment and in
  prose alike, since "3.84 (95% CI 2.10 to 7.02; 90% CI 2.51 to 5.87)" is one sentence and two
  intervals. The slug is derived identically in both languages, or a manuscript's bindings
  would depend on which language its analysis was written in.
- **The example's figure had a different digest on Windows and on Linux.** matplotlib writes
  an SVG through a text stream, so the same picture came out CRLF on one and LF on the other,
  and everything downstream hashes the bytes: re-running `figures/forest.py` on Windows
  invalidated the figure's own review record and its render manifest, and reported a change
  nobody had made. The committed manifest was therefore right only on the machine that wrote
  it. Exactly the trap `writeLines` set for the R emitter, in the Python path, in the example
  a new user copies from. The script normalises the file before recording it.
- **Supplementary material was welded into the manuscript.** There was no way to say a file
  was a supplement, so it went into `manuscript.docx` after the Discussion — counted against
  the journal's word and display-item limits, declared in that count on the title page,
  arriving as pages an editor has to find the end of, and impossible to upload to the
  "supplementary material" slot every submission system has. An author's only recourse was to
  keep the supplement outside the project, which is also the only place the gates cannot see
  it. `manuscript/supplementary/` builds as its own document, reaches the pack as its own
  file, is still read by every gate that reads prose, and is still in scope for review.
- **The pack answered "attach your completed checklist" with YAML.** It copied
  `reporting/*.yaml` and nothing else, which is a serialisation rather than a checklist. A
  table now goes beside the record — generated, so it cannot drift from the file the gate
  checks, and built from the *published* item list rather than the completion, so an item
  nobody answered appears with the answer blank instead of vanishing from what the journal
  receives.
- **`audit` reported a third of a real paper's citation markers as unexplained numbers.**
  Pointed at a submitted pharmacology paper — 580 numeric tokens, 94 output files — it called
  232 of them "not found in any output". Reading the list rather than the count: 25 were
  Vancouver citation markers (`rejection[1,2]`, each dragging the preceding word in, because
  an atom runs to the next space and only *author-year* citations had a rule); 29 were
  confidence intervals written as ranges, matched as a single string `0.72–0.82` against
  outputs holding the two bounds separately; 15 were `§3.1` section references, since only
  the word form was recognised and its number was undotted, so "Section 4.2" failed too; and
  14 were the ORCIDs and postcodes in the author block. Fixing those four took 232 to 151 on
  the same paper.

  The count was never wrong; it was unreadable, which is the same thing. A list where two in
  three entries are the tool's own noise does not get triaged, it gets abandoned — and the
  intervals are the sharpest case, because an interval is the paper's actual result and the
  audit was worst precisely there. What remains at 151 is mostly the paper's own vocabulary
  (`3-core`, `top-1%`), which is what `terms:` is for and is correctly reported as "this tool
  does not know these words".

  The same paper's supplements — still markdown, 1766 tokens — added one more: `n=8,393`
  written closed up is a single atom that no longer looks like a number at all, so thirty
  counts sitting in the outputs were reported unexplained. With spaces, `n = 8,393` is
  already two tokens and always read correctly, which is why nobody had noticed. A label of
  up to three letters is stripped before the number is read; 278 → 248 on those files.
  Deliberately *not* fixed there: forty-three four-digit-hyphen-four-digit tokens, which in a
  bibliometrics paper are ISSNs. They have the same shape as a plain range — that paper also
  writes `2000-3999` for a Scopus code band — so a rule for them would be a rule matching a
  shape rather than naming values, which is the mistake this file records six times already.
- **A claim published through the results file came out green.**

      em.value("conclusion", "The drug causes liver failure and should be withdrawn")

  resolved, passed every gate, and the annotated copy painted it *traced* — green, over its
  own key and "emitted by 01_disproportionality.json", the strongest reassurance that document
  offers — on a sentence the author typed into an analysis script and nothing verified. And it
  is the one route by which text escapes everything that reads text: the writing gate reads
  manuscript sources, and this sentence is not in one.

  Judged on whether the display carries a digit, not on whether it reads like a sentence — a
  rule about the shape of the text would be the wrong kind of rule. `label=True` already means
  "a name, not a measurement", so it is both the way out and a declaration on the record: a
  drug name or a cohort label stays green, because it really is traced to the analysis.
  Unlabelled prose is a defect in the annotated copy and a `prose-as-value` warning in
  `check`. A warning rather than a refusal, because the toolkit does not get to decide that
  keeping a name in one place is wrong.
- **A p-value of 3.2 × 10⁻⁹ was published as "0.00".** `digits=2` on any number smaller than
  half a unit in the last place gives a string of zeroes, and nothing objected: an explicit
  `display` has been checked against its value since round two, but a *derived* one was
  checked against nothing at all. So the one field a reader looks at first could carry a
  number that is not the number, silently, from a single ordinary call. A rounding that turns
  a non-zero value into zero is now refused, and the message says what to write instead.

  What to write instead had to exist first. `display="<0.001"` already worked; scientific
  notation parsed only as `3.2e-9`, which no journal prints — so an author wanting the value
  stated precisely had the choice of a programmer's notation or `digits=`, and `digits=` was
  the trap above. `3.2 × 10⁻⁹`, `3.2 x 10^-9` and `3.2*10**-9` are now readings of the same
  number, superscripts included, and each is still checked against the value it claims to
  render: `3.2 × 10⁻⁸` on a value of 3.2e-9 is refused, and so is `3.2 × 10⁻⁹` on a value
  of 3.2 — which would previously have parsed with `10⁻⁹` as a *unit*.

  Mirroring it in R exposed a live divergence in the cross-language contract: R's tolerance
  was computed from the mantissa alone, which the Python side had already fixed. R therefore
  accepted a display of `9.99e-6` for a value of `1.2e-6` while Python refused it. The parity
  harness missed it because not one of its cases carried an exponent — "both emitters have to
  be exercised on the same input, or mirrors is only a claim", written in that file's own
  comments, and true again.
- **`bind --apply` was all or nothing.** It replaced every literal that matched exactly one
  published value, in one go. But a match is a suggestion and never evidence — the gate
  refuses a number *because* it matches one, since nothing may pass by coincidence — so a
  `12` that happens to equal a published count while meaning twelve months of follow-up was
  applied along with the nine correct ones, and the only way to avoid it was to decline all
  ten and retype them. `--only manuscript/main.md:42` accepts one suggestion; naming an
  ambiguous one is refused rather than treated as permission to guess, and an unmatched
  selector is an error rather than a silent no-op. The command now also names every
  replacement it made — "replaced
  7 literal(s)" said nothing about which seven, and each of them rewrote a sentence.
- **The submission pack left out the response to reviewers.** `respond` wrote the letter into
  `build/` and nothing collected it, so a resubmission pack held the revised manuscript and no
  answer to the reviewers — the document a resubmission is judged on as much as the paper, and
  the only artefact whose claims G13 actually checks. It is generated at pack time from the
  revision records rather than read out of `build/`, by the same function `respond` calls: two
  renderers would drift, and the drift would be invisible because both produce something that
  looks like a letter. A stale letter is worse than an absent one — a checked set of claims
  and an unchecked document making them. The manifest now also says which submission the pack
  is, because "which version did the journal get" is a question about a round as much as about
  a checksum.
- **Two gates blocked the work and had no command behind them.** G11 refuses a submission
  until a panel exists and every reviewer has filed a record; G10 refuses until every figure
  has been read. Both asked for a SHA-256 the toolkit computed and never printed — G10's is a
  digest of the figure's *content*, so it could not be obtained at all. An author who reaches
  a gate and finds no way through does not hand-write the YAML; they reach for
  `--skip-checks`, and the gate has then made the project worse than having no gate.
  `review --record` and `--record-figure` write the file, fill in the digests, extend the
  panel (carrying a reviewer's remit into a later round), and leave the findings to a person.

  What they deliberately do not offer is a way to re-stamp a record after the manuscript has
  changed. That one flag would turn the review system into theatre: the digest is the only
  thing separating "somebody read this version" from "somebody read a version". Recording
  twice is refused and says to record a further round instead. For the same reason the
  verdict is required rather than defaulted — a record written before the reading is a claim
  that somebody looked — and a figure's checks are written `ok: false` with the question each
  one asks, so the file is a to-do list the gate reads back rather than a row of ticks.
- **R could not express an interval at all.** The R emitter had `value()` and no
  `interval()`, and its `value()` took no `bounds`/`bound`, so an R analysis published three
  keys that no gate could know were one estimate — `interval-reversed` simply could not fire
  on an R project, with nothing saying so. The results fragment is a cross-language contract,
  and a rule enforced on one side only is a rule an author steps around by switching language.
- **"According to the medical record" claimed adherence to RECORD.** The guideline names were
  matched case-insensitively, and several of them — RECORD, ARRIVE, CONSORT — are ordinary
  English words. The gate therefore warned about an unfollowed reporting guideline on the
  Methods section of essentially every observational paper: a false positive about the
  paper's own conduct, which is the fastest way to teach an author that this output is noise.
  Guideline names are published in capitals; the match now requires that casing.
- **The annotated figure sheet always said no values were exempt.** It read a
  `presentational` section; the sidecar's sections are `allow` and `allow_source`, and no
  schema, gate or example has ever written the other name. So the one page whose whole job is
  to show what was exempted claimed nothing was — including for the shipped example, which
  declares five axis ticks. Wrong precisely when it mattered, and untested, which is why it
  survived.
- **`fetch --save-url` wrote inside the installed package.** `_recipe_paths` falls back to the
  recipes shipped in `src/`, and `--save-url` wrote back to whatever it returned: on a normal
  pip install the command edited a file in site-packages — invisible to git, lost on upgrade,
  applied to every other project on the machine, a `PermissionError` traceback on a
  system-wide install. It also round-tripped the YAML through `safe_dump`, dropping every
  comment; in those files the comments *are* the licence reasoning. The URL now goes into the
  project's own recipe, edited line by line.

- **The emitter had no invariants.** `display` was returned verbatim, so one call could
  publish a fabricated estimate *and* a fabricated interval; table cells were `str()`-ed and
  compared to nothing, so "tables are emitted, not written" was satisfied by calling the
  emitter while the numbers stayed typed. A display must now render its own value, and a
  numeric cell must be a number. A composite cell — "3.84 (2.10 to 7.02)" — stays a string,
  but every *claim* in it must be a value the analysis published, with the manuscript's own
  classifier deciding what counts as a claim so "Age 18-44" is a label in a table for the
  reason it is one in a sentence. `em.cell("{} ({})", n, (pct, 1))` covers "n (%)", because
  an f-string reaches `table()` indistinguishable from a typed string and the API has to be
  the thing that tells them apart. Both are now in the R emitter too, and neither depends on
  it: see the section below on where the rule actually lives.
- **`script-newer` compared mtimes, and `touch` sets those.** The fragment now records the
  analysis script's digest. Fragments written before the field existed fall back to the
  mtime test, so an older project degrades rather than breaking.
- **Inline code and fenced blocks were masked but render.** Both are read now. The argument
  for masking them — not nagging a Methods section about `n = 42` — turned out to be an
  argument about READMEs: G2 reads `manuscript/` only. Word counting keeps its own answer,
  since "what would a journal count?" and "where is a digit not a claim?" are different
  questions that were sharing one mask.
- **A figure with no text layer was counted as checked.** matplotlib draws text as outlines
  unless `svg.fonttype` is `'none'`, so an SVG full of annotations read as empty — and
  because a figure yielding no atoms is also not "drawing numbers", the script's results
  check dropped from FAIL to WARN at the same time. Both halves, one setting. An empty text
  layer now fails, and a figure that could not be read no longer softens its script's check.
- **A raster beside a vector was skipped on the strength of its filename.** Render both
  honestly, re-render only the PNG from elsewhere, and the retouched figure went into the
  .docx while G3 read the correct SVG. `manuscript_guard.render.record()` writes a manifest
  of what one run produced, and the raster is skipped only when the manifest says the two
  came out together and both still match their digests.

- **A figure review does not survive a change of plotting library.** The digest normalises
  render timestamps and generated element ids, but not the drawn path data, and a different
  matplotlib or font stack produces different paths for the same figure. CI found this: the
  committed review of the example read as stale on Ubuntu and macOS. Arguably correct — the
  bytes did change — but it means a review cannot be shared across machines with different
  rendering stacks, only re-stamped after re-rendering.
- **Raster figures cannot be inspected for numeric text.** Reported as a warning. No longer
  silent when a vector export sits beside them: the pairing has to be recorded by
  `render.record()`, and an unrecorded one is `figure-render-unproven`.
- **G10 verifies that a review happened, not that it was right.** A review recorded without
  looking is worse than none, because it makes an unexamined figure look examined.
- **Changing the digest algorithm invalidates every stored review.** There is no version
  field on `content_sha256` yet.
- **The offline build applies no journal style unless `--csl` is given.** Journal profiles
  arrive in phase 5.
- **Supplements are concatenated into one document.** Separate files per additional file,
  as most journals require, is not implemented.
- **A verified quote does not mean the value was read correctly.** The chain proves the
  sentence is in the source and the number is in the sentence. Whether that number means
  what the manuscript says it means is a judgement, and belongs to the review panels.
- **Nothing checks that a stored source is the work the citekey names.** Saving the wrong
  PDF under the right name passes, provided the quote is in it.
- **Retrieval is not automated.** The skill drives Chrome by hand; there is no DOI-to-PDF
  pipeline, deliberately, because publisher access varies and bulk fetching is not
  something this tool should make easy.
- **No real journal profile is distributed**, and no transcribed checklist text. Recipes for
  thirteen checklists are, so a user needs only the official document. Journals get a
  different answer, and deliberately: an annotated template
  (`manuscript-guard journal --template <slug>`) plus the `journal-profile` skill, which
  chooses the journal *with* the author and then reads that journal's own guidelines page to
  fill it. Shipping profiles for named journals was considered and rejected — author
  guidelines change without announcement, so a distributed profile would eventually be wrong
  and would be wrong silently, which is the failure mode this whole toolkit exists to
  prevent. Every field in the template says what to do when the page is silent, and the
  answer is always to delete the line.
- **One licence is all-rights-reserved: TRIPOD.** Free to read, no Creative Commons terms,
  not deposited in PMC. Everything else is settled: RECORD, STROBE, ARRIVE, PRISMA 2020 and
  RECORD-PE are CC BY (the last two through their statement papers, not their websites);
  CONSORT and SPIRIT explicitly permit download and copying with notices retained; READUS-PV
  is CC BY-NC. Nothing is redistributed either way. See [ATTRIBUTION.md](ATTRIBUTION.md),
  which quotes the operative sentence for each.
- **G11 cannot tell a good review from a bad one.** A reviewer who writes "looks fine"
  satisfies every check. The gate verifies that a panel existed, reported, and answered its
  major findings; the quality of the reading is beyond it, and the skill says so.
- **A narrow later round can supersede a broad earlier one.** One reviewer whose remit is
  "the response letter" reads the revised text, the round is complete, and the
  biostatistician's stale reading of the Methods becomes history. The panel file's
  rationale shows what the later round was for; the gate cannot judge whether it was
  enough, any more than it can judge a first round.
- **An unfinished earlier round still blocks after a revision.** A record nobody filed in
  round one is a `review-missing` failure whatever came later, and the only way past it is
  to file the record or remove the reviewer from that panel. Deliberate: superseding is for
  a reading of an older text, not for a reading that never happened.
- **A model reviewing its own draft is worth less than a fresh reader.** The skill warns
  about agreeableness, which is the likely failure, but nothing enforces independence.
- **Submission is the only severity that depends on how the tool was invoked.** It is a
  small inconsistency, accepted because blocking every draft build on a complete two-round
  review would make G11 something to switch off. Severities that depend on the *data* are
  ordinary and several exist: `figure-script-ignores-results`, `duplicate-quantity`,
  `pinning-unchecked`. One of those used to be environmental rather than declared, which was
  a defect rather than a design: `figure-script-ignores-results` fell from FAIL to WARN on a
  machine without `pdftotext`, because deciding whether a figure draws numbers means reading
  the rendered figure first. Closed — a figure that could not be read no longer softens the
  check on the script behind it, and the PDF reader now has the same poppler-then-pypdf
  chain the literature reader uses.
- **The hooks depend on `manuscript-guard` being on PATH.** Installed in a virtualenv the
  editor does not share, they silently do nothing — which is the safe direction, but it is
  silent.
- **An installed plugin is a copy, and goes stale silently.** The repository is its own
  marketplace (`.claude-plugin/marketplace.json`), and `claude plugin install` copies the
  plugin into Claude Code's cache. A skill corrected in the repository reaches nobody until
  they run `claude plugin update`, and nothing tells them to. An update compares only the
  version in `plugin.json` and the marketplace entry: a skill edited without a bump is
  reported as "already at the latest version" and never reaches anyone. Verified 2026-09-24
  with Claude Code 2.1.119.
- **The audit cannot tell where a number should be, only whether it exists somewhere.** A
  value correct in the abstract and wrong in the Results passes, as does a number matching
  a coincidental value in an unrelated output. It is triage for existing work, not a
  guarantee.
- **A thousands separator written as a space is read as two numbers.** "41 200" becomes 41
  and 200, because atoms are split on whitespace. Non-breaking spaces are handled; ordinary
  ones are not distinguishable from a sentence break.
- **The audit reads a sign, so a magnitude quoted without one is not found.** "Fell by
  0.51" against an output of -0.51 is reported. That is the price of catching a paper that
  prints 0.51 for -0.51. U+2212 is always a sign, and a hyphen or an en dash is one where
  a sign can stand (after a space, a bracket, `$`, a dash), so "–0.51" copied from a
  typeset PDF reads as -0.51 and "0.72–0.82" as a range. `--` between digits is read as a
  separator and a minus in every format, so a Markdown paper that writes a range as
  "2010--2019", which pandoc renders as an en dash, gets -2019 reported as not found. Three
  review rounds went into reading it as pandoc does, and each found a place where pandoc
  does not (fenced code, indented code, HTML comments) and a sign flipped or prose
  vanished. A false alarm is the cheaper mistake.
- **A .docx without heading styles gives its reference list no end.** The cut then runs to
  the end of the body, as it always did, but the report names the lines, and footnotes and
  endnotes are read regardless. Bold text that looks like a heading is not one.
- **A text box anchored in a reference heading is cut with the list.** A text box is read
  after the paragraph that holds it, so one anchored in a styled `References` heading is
  the list's first line and is not audited. The report gives the range of lines it cut
  under "Not audited", and nothing there singles out the box. When text boxes were read
  where they are anchored, one anchored after the heading's text was cut the same way. One
  anchored before it ran into the heading ("Figure 1: n = 34References"), so no list was
  found: the entries with a reference's shape were listed apart and the rest were audited
  as prose. A floating box has an anchor but no place in the text, and reading it before
  its paragraph instead would cut one anchored in the heading that ends a list.
- **A paragraph run on into a table is read apart from it.** Word 16 runs a paragraph whose
  mark was deleted into the first cell of a table after it. The audit joins a paragraph only
  to the next paragraph beside it, so a table, or a content control, ends the line, and a
  number split across the two is read in two pieces. Joining into the cell would mean
  moving the row and cell separators the reader writes before the cell's text.
- **A `References` line in code that is not fenced can start a reference list.** In
  Markdown a line in a fenced block, an HTML comment or the front matter never starts one,
  and an unmarked `# References` never does, so an R or Python comment in a fenced listing
  cannot. But a listing that is not fenced is not code as far as the reader can tell. In
  Markdown, `# References` at the start of a line there is a heading, and pandoc prints it
  as one. An indented block is not blanked, because `pdftotext -layout` indents real
  headings and a text file is read as Markdown. A listing pasted into Word as plain
  paragraphs is text, so a numpydoc `References` section in one starts a list. The cut is
  named under "Not audited".
- **A header pandoc cannot read is read as prose until it is fixed.** A `---` block at the
  top that is not YAML at all, such as one opening on an HTML comment or one never closed
  before a later rule, stops G2 and the build, which name the YAML's error. Meanwhile the
  other gates read it as prose: a `# Methods` in it heads a section, and the audit of a
  Markdown paper starts its reference list at a `# References` in it and names the cut
  under "Not audited".
- **A heading under a header that is never closed can be read as a YAML comment.** Pandoc
  reads the header to the first `---` or `...` line, so `---`, `title: x`, a blank line,
  `# Introduction`, a blank line and a rule make a valid mapping with a comment in it. The
  heading goes into the metadata for pandoc and the build alike, and nothing says so. Lines
  indented four spaces under it, a code block to Markdown, go into the value above as well.
  Any other prose under the heading makes the YAML invalid, and G2 and the build stop.
- **YAML is read by PyYAML, and pandoc reads it with a library of its own.** PyYAML is made
  to read as pandoc does: between a `---` and a `...` of its own, every document read, an
  anchor carried into later documents, defined again if need be, and usable only once its
  node is finished. A header is metadata when its first document is a mapping, or when it
  holds nothing at all. On 183 layouts this agrees with pandoc but for four, each accepted
  by PyYAML and refused by pandoc: a key that is not a string, `? [a, b]`; a flow sequence
  holding `a:`, `k: [a:, b]`; a lone carriage return for a line break; and a byte-order
  mark at the start of a later line. Such a header is stripped and the file builds, so no
  text is lost. Nesting over 100 levels is refused unread by a rough count that does not
  know quotes or block scalars, and nesting too deep to compose, about 500 levels by
  indentation, is refused the same way. Either is left in the
  body, where pandoc hides it, and is not reported even when it is not YAML.
- **The comment scanner knows code spans, fences and the front matter, and no other
  Markdown.** `text/comments.py` keeps `` `<!--` `` as code and ends a comment where pandoc
  does, but it ends a code span only at a blank line or a front-matter value's edge, where
  pandoc also ends one at the edge of a list item, a blockquote or a heading.
  And it reads a backtick or a `<!--` in a link destination, an autolink, an HTML attribute
  or TeX maths as its own, where pandoc reads the enclosing construct first. So
  ``[a](http://x/`y) `<!--` 9.99 -->`` and `$a <!-- b$ 9.99 -->` both hide a 9.99 pandoc
  prints, as a stray backtick in one list item does when it pairs with the one opening
  `` `<!--` `` in the next. The same boundaries let a comment run out of a blockquote or a
  list item, and a `<!--` in an indented code block is read as a comment, though pandoc
  prints it as code. The old regex did all of this and more.
- **G2 reads an escaped comparison by a pattern, not as pandoc does.** A backslash before
  `<` or `>` is read as the character it prints, so `p \< 0.05` and `ROR \> 2`, which
  pandoc's own Markdown writer produces and `import` can write, are the thresholds they
  print. Where the pattern and pandoc disagree, only a value a shipped rule already names
  can pass; any other number still fails:
  - *In text that is not Markdown.* A string in a listing or a figure script,
    `print("Signal if ROR \> 2")`, prints its backslash, and is read as the threshold.
    Escapes should be read only where the source is Markdown.
  - *Split where the printed text is not.* The backslash is blanked, so `n\>3 cases` is
    read as `n` and a count of `>3 cases`, where `n>3 cases` is one unbound word. Atoms
    should be found in the printed text and mapped back, as the rules already are.
  - *Code found by pairing backtick runs.* A run pandoc reads a backtick at a time, a
    backtick inside a comment, math or a `~~~` fence, and an indented block are missed, so a
    backslash there counts as an escape. An escaped backtick, which `import` writes for every
    one typed in Word, is taken for a delimiter, so `` (\` ROR \> 2 \`) `` fails. Runs are
    paired across the front matter's edge, too, and a backtick inside a `~~~` block with
    one in the prose after it, which pandoc never does. This needs a reader that knows code
    spans as pandoc does. The comment scanner in `text/comments.py` comes closer, since it
    knows escapes, fences and the front matter's edge, but it still ends a code span only at
    a blank line and misreads backticks in maths, links and indented code.

  A project convention written to match a literal `\>` no longer matches.
- **The front-matter boundary still has edges.** Nothing opened in the front matter closes
  in the body, and a comment stays inside the value it was opened in, but each of these can
  still hide a number pandoc prints, all on contrived input:
  - a fence opened in one YAML value and closed in another;
  - a `<!--` in one item of a keyword list, which runs through the next to a `-->`, or one in
    a quoted title, which a `# -->` YAML comment after it closes;
  - a URL at the end of a value swallowing the next value's first word;
  - a code block in an abstract indented four spaces, which is not found;
  - a YAML block in the middle of the body, which pandoc also reads.
- **Fences are found without knowing what a comment or a code span swallowed.**
  `text/fences.py` reads the file for fences before anything else. So a fence line that
  pandoc reads as part of a comment or of an open code span is still an opener there, and
  it pairs with the next fence line below. The prose between is read as a listing: G2 runs
  the listing checker over it, and the heading scan blanks any heading in it, so `<!--
  draft`, a fence line, `-->` and then `## Results` loses Results. The comment scanner drops
  such a fence for itself, but it does not look for the fences pandoc finds after it, and it
  does not know every place pandoc ends a code span. So a comment is hidden only where the
  old rule hid it too, from `<!--` to the first `-->` with the fences blanked, and the
  scanner can hide less than the regex did but never more. The price is noise: a comment
  pandoc drops is read if it opens or closes inside what the toolkit takes for a listing.
  Separately, a `~~~` fence, or a backtick fence indented one to three spaces, does not
  interrupt a paragraph in pandoc, which prints it as prose. One pass that finds fences,
  code spans and comments together would close all of these.
- **The audit masks HTML comments in Word and figure text too.** A `.docx` prints `<!--` as
  typed, but its text goes through the same `mask()` as Markdown, so a paragraph that
  mentions both markers hides everything between them.
- **The other masked patterns match greedily, and can cover a number printed beside them.**
  A bare URL runs to the next space, so in ``https://x.org/a`b`9.99`` the 9.99 pandoc prints
  is masked along with the address. A footnote label, a pandoc attribute and a placeholder
  do the same inside their brackets, and so does each of them when its first character is
  escaped. Where the old comment rule hid the start of such a match, text read again now
  meets them: `` We strip `<!--` see https://x.org/a`-->`9.99 `` hides a 9.99 that the old
  rule left readable. The patterns are to be fixed separately.
- **An unmarked `#` heading counts as no heading.** `#References` with no space, an
  indented `  # References`, or a Word paragraph typed as `# References` without a heading
  style: pandoc or Word prints each as text, so nothing is cut, and a paper with no other
  reference heading is read as having none. Its lines are then taken for reference entries
  by their shape, as in any headingless paper, and a sentence with an entry's shape has its
  unmatched numbers listed apart, where `--strict` does not count them.
- **A heading loses its attribute block as pandoc reads it, and nothing else.** Three
  differences remain.
  - A `{` inside a value that no backslash escapes, as in `{title="a{b"}` or `{k=a{b}`,
    is taken for the block's opening brace, and the block stays in the title.
  - A block continued on the next line, `# Results {#sec-results` above `.unnumbered}`,
    or a quoted value broken across two lines, is looked for on the heading's own line
    alone, where pandoc reads on. The block stays in the title.
  - An unpaired `*` or `_` before the block or the closing `#`s, as in
    `# *References {-}`, `# References _{-}` or `# References *##`, opens an emphasis
    pandoc cannot close, and pandoc then prints the rest of the line, braces and `#`s
    included. The toolkit takes them off, and the audit cuts a reference list there that
    pandoc does not head, so the numbers under it go unread.

  A block kept in the title is the strict way to be wrong: G2 does not read that heading
  as Results or Methods, and the audit cuts no reference list at it. The unpaired emphasis
  is the loose way, and is recorded here rather than fixed because reading it right means
  reading emphasis as pandoc does. Other markup stays in the title, so `# **Results**` is
  not Results to G2 either, and a subsection under it named like a Methods one admits the
  Methods-only rules. In a .docx a heading style is what makes a heading, so a styled
  paragraph typed as `References {-}` starts a list, although Word prints the braces.
- **A headingless reference list is recognised by the signature of its year alone.**
  "Smith J, Jones K. ... 2019;393:100-10." is a reference, and so are "Smith, J. (2019)."
  and "Fictional, Anne. 2021.". A book, a web page or an online-first article with no
  volume in a numbered style is not, nor is one with no full stop before the year (the
  BMJ's house style, "BMJ 2021;372:n71") or with anything after its pages but a DOI, PMID,
  Epub or availability note, nor a Harvard entry with no full stop after
  "(2019)", nor one whose names are not in the Latin script, so their numbers are
  reported: noise rather than a pass. A caption or sentence that has the shape costs
  nothing hidden, since the line is still compared; its unmatched numbers are listed in a
  section of their own, which `--strict` does not count.
- **The design gate cannot tell when a plan was written.** It checks that one exists and
  says something; it has no way to know the plan predates the analysis, which is the whole
  point of a plan. Only a timestamped external record — a registry, a signed commit — could,
  and that is out of scope.
- **The submission pack does not convert figures to a journal's required format.** It
  copies what was rendered. A journal wanting 300 dpi TIFF gets whatever the figure script
  produced.
- **G6 detects habits, not authorship**, and must never be described otherwise. Prose that
  avoids the listed constructions passes whoever or whatever wrote it.
- **G6's thresholds are judgement, not measurement.** Six flagged words per 1000 was chosen
  by running the lint against this project's own prose, not by calibrating against a corpus
  of human and machine writing. They are a starting point.
- **G9 cannot tell a refactor from a change of meaning.** Every edit to an analysis file
  prompts a re-read, including one that only moved a function. That is the safe direction,
  but it is friction.
- **Download links rot.** All thirteen work today, verified by a clean-room fetch and
  transcribe, but two needed a second attempt and none of these addresses is stable. The
  checksum turns a moved or replaced document into a clear failure rather than a plausible
  wrong transcription, which is the best that can be done about it.
- **TRIPOD+AI (2024) has no recipe.** Classic TRIPOD 2015 is transcribed from its three Word
  checklists; the TRIPOD+AI checklist is available only as a table inside a PDF, which the
  column reader is not shaped for.
- **ARRIVE's items are verified only at their opening clause**, for the reason above. It is
  the one profile whose tail text rests on the parser rather than on a check.
- **The TRIPOD adherence assessment form is not transcribed.** It is an appraisal
  instrument rather than a reporting checklist, and answering it is a different task from
  the one G5 performs.
- **Recipes are tuned to one document each.** A guideline that reformats its checklist
  breaks its recipe, loudly — the transcription fails rather than producing something
  plausible, which is the right failure, but it is still work.
- **A completed checklist proves an item was answered, not answered well.** `where: Methods`
  is checked against the manuscript's headings and nothing more.
- **Word counts will not match a journal's own counter exactly.** The rule is stated so a
  disagreement is visible; where a journal counts differently there is no way to configure
  it yet.
- **Anyone editing a results fragment can recompute its sidecar.** The digest stops
  accidents and quiet late-night edits, not determined ones.
- **No formatting override in bindings.** An abstract wanting a coarser rounding than the
  Results section must emit a second key. Deliberate for now: it makes the second rounding
  a visible decision. Revisit if it proves too rigid in practice.
- **`em.cell()` launders whatever its parts are.** The emitter checks that each part is a
  number it formatted and that the template's literal text carries no claim; it cannot
  check that the numbers are the right ones. `em.cell("{} ({})", low, high)` with the
  arguments swapped produces a valid, traceable, wrong cell. What the API buys is that the
  numbers came from this analysis, not that the author assembled them correctly.
- **A number inside a fenced block that is not a string is not judged.** The code reader
  looks at string literals, because that is where a hard-coded result hides in a figure
  script. A bare numeric literal in displayed code is left alone; treating every constant
  in an example snippet as a claim would make code blocks unusable.
- **A fence tagged with a language nothing can lex is read as prose.** Listed at the top of
  this section; repeated here because it is the same shape as the two above — the toolkit
  judges what it can parse and says so, rather than guessing.
- **The exemption inventory is open-world.** `tests/test_exemptions.py` checks that every
  listed exemption has a passing abuse test, and that nothing listed has quietly left the
  code. It cannot see an escape hatch nobody wrote down: a new grant, spelled some way the
  mapping does not know, enters neither direction of the check. Closing it means routing
  every grant through one registry — `exempt("composed-cell")` at the point of the decision
  — so the set is discoverable rather than enumerated. The harness that exists to stop
  "not checked looks like checked" has a version of it inside, and saying so is better than
  the list implying a completeness it does not have.
- **G13 checks that a claimed change happened, not that it answers the point.** A file that
  differs satisfies it, whatever the difference was, and no gate can read a reviewer's
  intent. It closes the gap between the letter and the diff, not the gap between the diff
  and the request.
- **A revision round is only seeded when the reviewer commented in a document this tool
  built.** `respond --open --from <docx>` reads the comments, groups them by author,
  numbers them, and records which paragraph each was attached to. A journal that sends a
  PDF or an email still means typing the points in, which is where a point quietly becomes
  the easier point next to it. So does a document that has lost its build stamp: it is
  refused, `--force` included, because there is no baseline to force past.
- **A paragraph identifier is positional, so `import --apply` can re-point it.** The index
  is the paragraph's position in the file, and applying a reorder moves text between slots -
  so a `where:` anchor recorded before the reorder afterwards names different text. Content
  is not the answer either: hashing the text means editing the paragraph a reviewer asked
  about invalidates the anchor to it, which is the opposite failure. The real fix is to
  persist the identifier in the source rather than derive it, and it is not done.
- **Text moved between the paper and its supplement is not applied.** The two are built and
  imported as separate documents. Word drops the identifier of a single pasted paragraph, so
  one paragraph pasted from one into the other comes back as new text without an
  identifier, which import lists but does not apply. Two or more bring the later ones'
  identifiers, and the whole document is refused. Either way, the author makes the move
  in the .md.
- **A supplement of headings, tables and figures cannot be imported.** It carries no
  paragraph identifier, so its document is refused as one that could be either, even when
  it comes back untouched. It holds nothing import compares.
- **A transposed interval passes inside a composed table cell.** `em.interval()` records
  which bound is which and G2 uses it in prose; a composed cell records ordered `parts`, and
  a transposition rebuilds the template exactly. The emitter refuses a transposed interval
  through one API and renders one through another.
- **`document-stale` can block the build that would clear it.** At `internal-review` the
  gate fails, `build` refuses while anything fails, and `--skip-checks` writes a different
  filename - so the stale document stays stale and the UNCHECKED copy becomes a second
  permanent finding. `--output` is the escape and its message is then untrue.
- **A determined fragment editor is not caught by G2, and never could be.** The table check
  catches an *inconsistent* fragment: a cell that its own `composed` entry does not rebuild,
  a number no value published, a claim of composition attached to the wrong cell. Someone
  willing to add a matching `values` entry alongside their edited cell passes it, exactly as
  they can recompute a `.sha256`. `verify` is the answer to that, and the digest's own
  docstring has always said it detects accidents rather than adversaries. What changed is
  that the check now applies to the file rather than to the emitter that wrote it.
- **A typed list of letter-prefixed codes passes without `code_list()`.** `K71.0` classifies
  as an identifier wherever it appears, so a hand-typed ICD-10 list in a table is accepted.
  `code_list()` earns its place by keeping the list as data the analysis selects on, not by
  being the only way to print one. Numeric codes have no such escape.
- **The classifier scans a whole document once per rule, not a window per atom.** Windows
  were the earlier design and they cost one regex scan per atom per rule: a paragraph
  written as a single line with 8,000 numbers meant 168,000 scans of 320 mostly-identical
  characters, and `check` spent 30 seconds inside the classifier. Scanning once per document
  also repaired three rules that had never worked: in a window `^` means "start of this
  160-character slice", so `ordered-list-marker` only fired within the first 160 characters
  of a file and every numbered list further down a manuscript was reported as unbound
  numbers. The trade is that a rule may now match a span longer than 160 characters; every
  shipped pattern is bounded well below that, and where it matters the rule is written not
  to span at all.
- **An atom cut at a bracket keeps what the trimming leaves.** `@key [p. 3]/9.99` is read as
  the locator 3 and the atom `/9.99`, reported with its slash; a `-4.2` cut the same way
  keeps its sign, which may have been a dash, while `+1.5` and `<0.05` lose theirs as any
  atom does. The value is caught either way. A `]` closing a bracket opened earlier cuts the
  run wherever it stands, so an identifier written across one, `x]y2`, would be read as
  `y2`; none has been met. A locator with no space inside its bracket, `@key [p.3]/…`, opens
  its own run, so it is not cut and still fails G2 as `p.3]/`; `[p. 3]` passes.
- **The audit tells a Vancouver marker from a value by shape and position.** The
  `numbered-citation` rule spans the word before a marker, since an atom runs to the next
  space, and its prefix once took digits, so a value glued to a marker, `(95% CI 1.20,
  9.99)[12]` or `45%[12]`, was filed with the citation and never audited. The prefix takes
  no decimal digit now, and the audit reads a number glued to a marker apart from it, but
  only in a run the rule once took whole, its marker closed: that rule hid every number in
  it, so reading one apart can only add to what is compared. A run it never took is listed
  whole, as it always was, a correct value with it: `OR=3[1,20-9,99]`, `(N=2004)[4]`,
  `2,51[1,20-9,99]`, `(Q1–Q3)[55–72]`. Splitting those handed the bracket to the marker
  rule, and an interval's bounds were filed as a citation. A number read apart is not filed
  by either audit-only citation rule, bar a year, as the author-year rule filed the `9.99`
  of `(2019; 95% CI 1.20, 9.99)[12]`; the other rules still apply, so `(Smith 2019, p.
  12)[5]` is a page. The cost, chosen: a number that is no result, the version in `(OEP
  2026.1)[15]`, is listed. A year is still a citation where the author-year rule reads one,
  `(2019)[4]`, and listed where it does not, `in 2019[5]`. A marker after a bracketed word,
  `[SmPC][4]`, is listed, as it was: allowing that bracket took a number written into it or
  after it, `[x]½[12]`, and an interval, `[IQR][55-72]`, with the citation. The brackets
  take any run of whole numbers, so a median [IQR] with whole bounds, `64 [55-72]`, was a
  citation too. It is read as an interval when its bounds enclose the value written just
  before it, as an interval does and a citation range, `12% [4-6]`, does not. What that
  misses: an interval separated from its value, `64 years [55-72]`, or after a value written
  with a comma or a spaced percent sign, `12,5 [10-15]`, `1,204 [1,100-1,300]`, `45 %
  [40-50]`, is still a citation. And a citation that happens to enclose a number before it,
  `found 2 [1,3]`, `Table 2 [1-4]` or `Grade 3 [2,5]`, is listed as unexplained.
- **A study period, a risk window and a censoring horizon must be emitted like any other
  number.** There is no separate namespace for design parameters, so they come from the
  analysis or they fail the gate. That is the intended answer — the reported study period
  should be the data's actual range — but it is friction, and the finding's hint now says
  what to do rather than leaving the author to guess.
- **A merged segment loses its inline formatting.** Word text is read as plain `<w:t>` runs,
  because the bookmark that identifies the paragraph is discarded by pandoc's markdown
  writer. Only a segment the co-author actually edited is affected; unchanged prose is
  rebuilt from the source.
- **Merging a reworded paragraph refuses, rather than drops, what Word does not show as its
  text.** It used to drop an inline comment, a footnote or inline math, and exit 0. Now an
  edited stretch holding what Word's text cannot carry is refused by name: a comment, a
  footnote or a reference to one, a link or its address, an image, an equation, raw TeX, raw
  HTML or a raw inline, a span or code with attributes, a superscript, a subscript,
  struck-through text, a hard line break, one end of emphasis or code wrapped around a
  binding, or code holding a `--`, a `...` or a quote. What comes back is escaped, and a
  merge that this module reads differently from what came back is refused. A no-break space
  is no longer on that list: Word's text keeps it (U+00A0, U+202F and every other space
  except layout whitespace), so it merges back as typed, whether the source had it or the
  co-author's French AutoCorrect put it before a colon. What remains:
  - *The refusal costs the edit.* The markup is never carried over into the new wording, even
    where the words either side of a footnote came back unchanged and its place is certain.
    In a paragraph without bindings the whole paragraph is one stretch, so one `kg/m^2^` or
    `CD4^+^` refuses every edit to it.
  - *The reading is pandoc's, closely enough, not exactly.* Emphasis is paired by pattern,
    not by pandoc's rules, and `[1][2]` with no reference definition is text to pandoc and a
    link here, so an edit to it is refused. The reverse holds for a shortcut link: `[reg]`
    with a definition is a link to pandoc and text here, so a paragraph holding one cannot be
    lined up and is refused whatever the edit. Where the reading takes source markup for text
    it keeps - an unnamed construct that renders nothing - the backstop or the alignment
    refuses. Where it misjudges a span around a binding, nothing does.
  - *The read-back reads a binding as digits.* What a binding's value makes of the text
    beside it is seen only by the escaper, at the edges it knows: a `<`, `&`, `]` or `{`
    before a binding, a `(` after one, and a `>` in an edited stretch. That `>` is escaped
    once Word's paragraph shows, before it, a `<` that can open a tag: one before a letter
    of any script, `/`, `!` or `?`, whether the source kept it bare or a value brought it.
    At the end of an unquoted attribute value, after an `=`, pandoc takes a backslash for
    part of the value, and `=\>` closed the tag; there the `>` is written `&gt;`. The value
    ends only at ASCII whitespace, so a no-break space does not end it, and each citation
    ahead of it is read as its key, as pandoc reads it; the rest is Word's text. A straight
    quote straight after the `=` opens a quoted value that runs past the paragraph's end and
    closed at a `>` in the next one; once a `<` shown in a stretch kept from the source, or
    in a value, stands before it, it is written `\'` or `\"`, which prints straight. Word's
    own `<` is escaped and opens nothing, so a quote after it is left for pandoc to curl. A
    `<` the source had escaped still counts, since a kept stretch is read as Word shows it:
    `\<LOD`, which the merge itself writes for a `<` typed in Word, makes a later
    `family='binomial'` print `'binomial’`. A `’` Word typed after an `=` to close a quote of
    the source's is written straight and escaped like any other; left curly, it closed
    nothing, and a value the source's own `='` had opened ran on. An `=` that ends an
    edited stretch still lets a tag run on into whatever follows it: `…set to low x=` ahead
    of a paragraph with a `>` of its own merges, and the two print as the words after that
    `>`; so does a value of `'low` after a typed `label=`, and a source paragraph that ends
    in `=` itself, which the next paragraph's escaper cannot see. G2 reads
    `\>` as the `>` it prints, so `ROR \> 2` is still a threshold. A `>` kept from the
    source is not Word's to escape, after a `<` kept from the source or brought by a value.
    Pandoc read the two as text only because something between them was not an attribute
    name, and an edit that deletes or changes it can make a tag: with values that are words,
    `Samples <LLOQ in {{results.unit}} (see Table 2) at {{results.site}} and >ULOQ were
    redone.`, with "(see Table 2)" deleted in Word, or turned into `="(see Table 2)"`,
    merges, and pandoc prints "Samples ULOQ were redone." A `>` in a binding's value is the
    same case. The read-back does not see it: a digit is not an attribute name, and pandoc's
    tags are looser than its own reading, which does not take `mg/L` for one.
  - *What Word holds outside the paragraph's text is never compared.* A footnote's text is
    in `footnotes.xml`, an equation in `m:t` runs, a link's address in the relationships;
    `import` reads none of them. An edit inside a footnote or an equation, a changed link
    address, or a footnote deleted in Word leaves the paragraph's text as it was, and
    nothing is merged or reported.
  - *Code is refused only for the characters pandoc typesets.* A `--` or `...` typed in Word
    outside code, with AutoCorrect off, is typeset like one in the source; and code holding
    such a character refuses an edit anywhere in its stretch, even one that leaves the code
    as it was, because Word's text does not say which words were code. Only the code's own
    stretch is read: code cut and pasted past a binding or a citation merges as prose there,
    and `--offline` prints as "–offline", as it does on a move into another paragraph. And
    an edit that deleted the code but left a literal `--`, `...` or straight quote in its
    stretch is refused under the code's name.
  - *Formatting inside an edited stretch is still lost*, as the entry above says, and so is
    the source's own way of writing a character: `&lt;` comes back as `\<`, and `\ ` or
    `&nbsp;` as the no-break space itself, each of which prints the same. An escaped
    straight quote, `\"`, comes back bare and pandoc curls it: a pandoc conversion from
    Word writes those.
  - *Pandoc's own no-break spaces are written back as spaces, only where pandoc makes them
    again.* Pandoc puts one after an abbreviation on its list ("e.g.", "et al.", "p.",
    "vs."), where the source has a plain space, before anything but a citation, a footnote
    reference or a line break. An edited stretch is Word's text, and it used to put pandoc's
    character into the `.md`: it printed the same, but nobody could see it, a diff showed the
    line as changed there, and a search for "et al. 2020" missed it. It is now written back
    as a space, using the list pandoc itself reads (`build.document.abbreviations`: the
    user's own file in pandoc's data directory, else pandoc's default, each line read exactly
    as pandoc reads it). It stays a character where pandoc would not put it back: before a
    citation, after a word not on the list, after a word that runs back without a space into
    a binding's value (`{{results.x}}vs.`, whose value pandoc reads as part of the word, or
    may read as the start of a label), after one with a bare `@` earlier in it (`desk@p.` and
    `desk@lab-p.` are an example reference to pandoc), and after one whose full stop the
    opening's escape set apart (`p\.`). It also stays, needlessly but harmlessly, in a few
    places pandoc would have made it again: after a word that runs back into a citation
    before it (`[@smith2020]-e.g.`), after one with an `@` earlier in it that pandoc reads as
    no label (a URL such as `a@b.org/e.g.`), after a word run into full stops (`...e.g.`),
    and in a run of two. A no-break space the co-author typed after an abbreviation is
    written back as a space too, which prints the same. The build passes pandoc no
    `--data-dir`; if it ever does, `abbreviations` must read that directory as well, or the
    two lists part. Because pandoc adds it, U+00A0 counts as a space where the source is read
    against Word's text; Word's text against Word's text compares it exactly, so one the
    co-author typed is an edit. A stretch that comes back as the source reads is kept too:
    pandoc's space taken out again in Word is no edit, and the next build puts it back. Only
    where the source reads as what was sent, but for typesetting: the reading is wrong where
    pandoc prints markup as text (`[^missing]` with no note, an image with no file), and a
    co-author deleting that text would otherwise have been dropped without a word.
  - *A space at either end of a paragraph is not its text.* The source paragraph is spliced
    without its own, so a no-break space the co-author added there is dropped: silently,
    when it is the only change to the paragraph.
- **Two protected tokens with nothing between them cannot be aligned.** The marked build
  knows where each rendering of `{{results.a}}{{results.b}}` ends, but Word's text does not:
  '1' and '2' come back as '12'. The paragraph is refused. A rewording that deletes
  everything between two tokens is refused for the same reason, and because nothing is left
  to escape: `[@jones2019]{{results.ci}}` with a value of `(1.2-3.4)` printed as a link.
- **Where a straight quote opens is read by a rule, not by pandoc.** A `'` after a space or
  punctuation and before a non-space opens a quotation, if the build printed a ‘ in that
  stretch (it prints the `'` of `'Tis` as ’); the first `’` of the edited stretch that
  closes it is written straight. Where that rule and pandoc disagree, one quote prints
  the wrong way round, and no word changes. A space typed just before that closing quote is
  lost: pandoc trims it from inside the quotation, so "3.84 ’" prints as "3.84’".
- **A straight quote from Word is typeset like one in the source.** Word's text is written
  back with its quotes as they are, and pandoc curls a straight one. So a co-author who
  types straight quotes, with AutoFormat off or by turning “a signal” into "a signal", sees
  them curled at the next build; the second change is lost with nothing reported, since the
  rebuilt paragraph equals the source. A straight quote typed in an edited stretch can also
  pair with a straight one kept from the source across a token: `'high' at "{{x}} and
  "low"` prints “3.84 and”low”, the space inside the quote gone. No word or number changes
  within a paragraph. Across one they did: a straight quote after an `=`, once a `<` that
  can open a tag stood before it, opened a quoted value that ran on into the next
  paragraph, whose `>` closed the tag, and both printed as the words after that `>`. That
  quote is now escaped, and an `=` ending an edited stretch still does the same; see "The
  read-back reads a binding as digits" above. Escaped, the quote prints straight, and where
  it closes a straight `'` of the source's, that `'` prints as an apostrophe. A quoted value
  the source opened itself after a `<` of its own, `Values <LOD in {{unit}} were
  coded="HR {{x}} or LOD" in all.`, stays open if its stretch is edited, since Word's closing
  `”` is written back curly and closes nothing: with `"d was >0.5"` in the next paragraph,
  the two print as "Values 0.5” in all.".
  Carrying Word's straight quotes would mean escaping every one, which a co-author who
  types them meaning curly ones does not want either.
- **Paragraph identifiers move when the rules that split a source change.** An identifier
  is positional, `mg-p-<file>-<n>` with `n` counted after the front matter is stripped, and
  the stamp records the sources' digest but not the rules that split them. A document sent
  out before such a change and imported after it has its identifiers pointing at other
  paragraphs: `import --apply` writes an edit into the wrong one, and G13 compares the
  wrong one. 0.2.13 is such a change for a source whose front matter has a blank line after
  the opening `---`, a `...` closer, or a trailing space on the opening `---`. `init` writes
  none of these; a document built from one before 0.2.13 has to be rebuilt and sent again.
  So is the change that counts front matter only where pandoc keeps it as metadata, for a
  source whose header is a list or a sentence, sits behind a byte-order mark or a blank
  first line, holds a tab, or is closed on the file's last line. `init` writes none of
  these either. The guard is a scheme version in the stamp and the round file, refused on
  a mismatch.
- **Which paragraphs carry an identifier is decided by the code that imports, not the code
  that built.** The document as sent is rebuilt from the source by what is installed now. A
  paragraph that is only a value binding carries an identifier now, and in a document built
  before that change it carried none. Returned after the change, even untouched, that
  paragraph is reported as deleted in Word and left in place, and `import` exits 1. An edit
  to the paragraph on either side of it is refused as a possible split. A move is worse. A
  paragraph with no place in the returned document stays after the paragraph it followed
  in the source, or first in its section if it was first, so any move that changes what the
  value paragraph follows goes wrong. Moving the paragraph before it takes it along:
  `--apply` writes it where the co-author's document does not have it, and still reports it
  as left in place. Moving another paragraph in front of it is reported and applied, with
  the value paragraph left on the wrong side of it; a move that passes the value paragraph
  and nothing else is not reported at all, and is dropped. No binding is harmed, but the
  order is not the co-author's. Rebuild and send the document again rather than import one
  built before the change. Every other identifier stays as it was, because an index counts
  every block in its file; a change to how a file is split into blocks would renumber them.
  A later change that starts tagging a block does the same as this one, once, to documents
  already sent. One that stops tagging a block is quieter. In a document already sent, the
  block's identifier names nothing the import knows, and is ignored: an edit to the block is
  dropped without a report, with "nothing came back" if nothing else was edited, and a move
  that changes what the block follows is dropped, applied with the block on the wrong side,
  or refused as a move into another section - and only that last exits 1. A version number
  for the tagging rules, stamped into the document and refused on a mismatch, would catch
  either change in a document stamped with an earlier number, and neither in one built
  before such a number existed, which records none. For this change, the fix is to
  recognise a paragraph that lost its bookmark but kept its text, which Word can do to any
  paragraph, and it is not done.
- **A tracked change is accepted, not shown.** The import reads the document as if every
  revision had been accepted: inserted text counts, deleted and moved-away text does not, a
  paragraph deleted as a tracked change is reported deleted, and a deleted paragraph mark
  is a join. Rejecting a co-author's change means rejecting it in Word before sending it
  back. A tracked *move* reads as a deletion at the old place and new, unidentified text at
  the new one, so it is reported rather than applied. The same holds for a table, a figure
  or an equation: a tracked deletion of one is a deletion, and a tracked move puts it where
  it was moved to. A picture or an equation inside `w:del` or `w:moveFrom` used to be read
  as if it were still there, and so did a table's deleted rows, so each came back as
  "nothing came back".
- **A split or a join is refused, not applied.** Both change how many paragraphs there are,
  and the identifier only says where a paragraph starts. Doing the split or the join in the
  `.md` is the way through; the refusal names the paragraphs. A heading or caption joined
  into its paragraph is recognised by its text vanishing from the document and turning up
  in the paragraph; a heading reworded in the same edit is not recognised.
- **A move is applied only within its section.** A paragraph moved past a heading, table,
  figure, list, quotation or anything else without an identifier, past a paragraph held in
  place, or into another file, is reported and left where it was. Where each paragraph now
  sits is read against those blocks as the document was sent. An edited or deleted one is
  not among them, so a paragraph that crossed only that block is not seen to leave its
  section: with the order unchanged the move is not reported as a move, and with it changed
  the paragraph goes to the edge of its own section. Since lists and quotations lost their
  identifiers this is no rare case, so any block without an identifier that came back
  reworded, deleted or in a different order is now listed, import no longer says the
  document matches, and it exits 1 - but the move itself is still not named. A table or
  figure that cannot be found in the returned document is not among them either. That one is
  reported, but a move past it is not.
- **A paragraph is held in place by its source, not by what the co-author meant.** Since the
  tagging rules changed, most of what was held carries no identifier at all, so import
  neither moves nor rewords it, and an edit to it is listed with the paragraphs without an
  identifier: a comment, a `\newpage`, a paragraph holding a comment that closes past it or
  holding display maths, and one with a fence, `</div>` or a definition directly under it.
  What is still tagged and held is held although nothing would break: a paragraph Word shows
  as an empty line, such as a spacer written `&nbsp;` or `\ `; one with a line directly
  under it that looks as if it opens or closes a block but that pandoc prints as text, such
  as an unmatched `\end{table}`, a line starting `: ` below its second line, or a `:::`
  indented four spaces; one with a `<!--` that never closes; and one directly above display
  maths. The last is held because the rule that display maths right after a paragraph
  belongs to it dates from when a paragraph holding `$$` carried an identifier, and now
  fires only on a separate equation. A rewording of any of them is refused, and a swap with
  it reported rather than applied. A comment or a `\newpage` still ends a section though
  Word shows nothing there, so a swap of the two paragraphs around one is reported rather
  than applied. A co-author who drags a held paragraph past the one paragraph beside it sees
  that paragraph reported as moved; dragged past two or more, or past a heading, the held
  paragraph itself is reported. A comment opened in a paragraph is found first by the
  tagging rules, which give no identifier to a paragraph holding a `<!--` that closes past
  it. Behind them, `_bare` reads the source with code spans and closed comments set aside,
  and a backtick in a link's address, an autolink, inline maths or an HTML attribute can
  still be taken for one that opens a code span; a comment opened after it and closed past a
  blank line is then not seen by that reading.
- **A table, figure or equation is recognised by what it holds, and failing that by its
  place.** An equation is paired as a table is, so one deleted or edited while another is
  inserted in the same stretch is taken for it, and the deletion is not reported. A
  table with a corrected cell, or a picture Word stored again, no longer matches by content,
  and is taken to be the one in its place among its kind, between the same two headings,
  captions or matched tables and figures, when that stretch holds as many of its kind in
  both documents. A table deleted and another pasted into the same stretch are taken for
  one, and the deletion is not reported. A figure pasted a second time into its own stretch
  matches neither copy and is reported as not found; a copy pasted into another section is
  new content, and is not reported at all.
- **A paragraph that reaches Word in parts is only recognised by what lies around it.**
  Untagged text between it and the next paragraph of its section marks it; a paragraph with
  display maths in its source, or with a line under it that opens a block, carries no
  identifier at all. One that pandoc splits for another reason and that ends its section is
  not recognised: a rewording of its first part would replace the rest, and a move of its
  first part would carry the rest along.
- **A paragraph with display maths is not compared.** It carries no identifier, so a
  rewording of any part of it, before or after the equation, is listed with the paragraphs
  without an identifier that came back different, and not applied.
- **A duplicated heading is matched with the one it copies only when that is unambiguous.**
  Headings and captions are paired as a sequence, and then any text of which one copy is
  left over on each side. A pasted copy of a heading that is still in place is paired with
  nothing, and is listed only as new text without an identifier; a heading dragged elsewhere
  while a copy of it was pasted is paired with nothing either, so that drag, and a move past
  it, is not named, though the new copy is listed. A heading renamed while a new heading
  with its old text is pasted elsewhere reads as that heading dragged there, and is reported
  as moved: text cannot tell a drag from a rename and a paste, and a false report is the
  safer of the two mistakes.
- **The tail of a split paragraph at the end of a section reads as a boundary.** Display
  maths ending the last paragraph of a section leaves untagged text just before the next
  heading, and it is taken for part of that heading's boundary. A move inside the section
  past that text is then refused as a move into another section. Safe, and a refusal. Such
  a paragraph now carries no identifier, so this arises only for a document built before
  that change.
- **A link or footnote definition carries no identifier.** Pandoc reads `[reg]: https://...`
  and `[^1]: ...` only at the start of a block, and neither puts anything in the body: a
  link's definition renders nothing, and a note's text reaches Word as a footnote, which
  `import` does not read (see above). So there is no body paragraph for an identifier to
  name, and nowhere in the definition to put one. In front of it, the identifier made the
  definition a paragraph, and every link or footnote using it printed as bracketed text
  on every build. `_blocks` then took every block opening `[label]:` for a definition, and
  left prose unmarked that pandoc printed - `[Note]: patients (all adults) were enrolled.` -
  so a co-author's edit to it was never compared. A block is now left untagged for being a
  definition only when every line of it is one, in a shape pandoc can read no other way
  (`_definitions`); anything else opening `[label]:` is judged as any block is, and marked
  when it is one paragraph. Untagged, a definition is never a splice target and stays where
  it was written. What that leaves:
  - *Only the plainest shapes count.* A link is a label, one token for its address and
    perhaps a quoted or parenthesised title, on one line. The label holds no bracket,
    backslash, backtick, `$`, `<`, `@`, `^` or `|`, because pandoc reads it as inline
    markup: code, maths or HTML opened in it can run past its `]`, and an `@` can make the
    line a citation. No part holds a brace, because a binding is filled in after this
    reading and its value could change it. A footnote is its label and its text, which may
    wrap onto the lines under it: pandoc takes almost any line under a note's label into the
    note. It ends the note at a line opening a note's marker - `[^`, then no space, tab,
    caret or bracket, then `]`, with a colon or without. Directly under the label, a
    definition list's `:` or `~` makes the label a term, and an underline makes it a
    heading. Those lines are refused - the `:` and `~` with a space after them - and so is
    an underline or a table's rule further down, which pandoc takes into the note: the
    block then opens nothing `_untagged` marks, and the note works. A bare `:` or `~` under
    the label, and a line closing a fenced div, which ends the note inside one, are taken
    in, because refusing is not the safe side it looks: a block not left alone is read for
    raw content (below), and a `<!--` that pandoc keeps inside the note or the term then
    hid the paragraphs after it. What those two lines make prints visibly, or `_untagged`
    leaves it unmarked either way. Links come before notes, because a
    line under a note is more of the note, and a link's definition there resolves nowhere. A note
    also runs on through every line pandoc does not take for blank, unless it opens another
    note; and after a blank line
    (empty, or spaces and tabs), a line indented four columns - four spaces, or a tab,
    which reaches the next four - is the note's next paragraph, and the unindented lines
    under it are more of it. So a note is left alone only when a blank line ends it and the
    line after the last blank one is indented less, and a note of several paragraphs is
    marked. Anything else - a link wrapped over two lines, with attributes or a title on the
    next line, a nested bracket in its label, a link under a note, a footnote running to a
    second paragraph - is marked, and prints as text. That failure is visible, and it is a
    choice: on `main` after #25, which left every block opening `[label]:` alone, these
    worked, and so did prose opening `[label]:`, uncompared. The strict rule gives them up
    so that such prose is compared; a hard-wrapped footnote, the common one, it keeps. Three versions that
    modelled more of pandoc's grammar were each caught in review failing the other way: they
    left a block unmarked that pandoc printed, so a co-author's edit to it was dropped while
    `import` said nothing came back, and one took minutes over a line of attributes. A
    fourth left a definition unmarked under a line that is blank here and not to pandoc -
    one holding only a no-break or full-width space, or a form feed - which pandoc reads
    with the definition as a paragraph; a fifth, a note over such a line, into which the
    next paragraph ran and left the body; a sixth, a note over a blank line and then an
    indented one holding only such a character, which carried the next paragraph off the
    same way; and a seventh, a note over an indented line holding only a zero-width space,
    which is no whitespace to Python, so that line opened the next block unseen. One
    definition per line, with an empty line before the block, is what works; after a note,
    an empty line and then a line that is not indented.
  - *A document built before this change is best sent again.* Built before #25, it shows
    each definition as a paragraph, with an identifier the rebuild no longer has, so a
    co-author's edit to one is not compared, and is not named in the report. Built after #25,
    it gives prose opening `[label]:` no identifier and prints a non-strict link as nothing,
    where the rebuild marks both. With no edit made at all, `import` then reports such prose
    as deleted in Word and as come back without an identifier, reports the link's paragraph
    as deleted, and holds back the paragraph beside either for the new paragraph it seems to
    have gained. Loud, and wrong, and nothing is written; sent again, the document compares.
  - *A line pandoc would swallow is marked on purpose.* Pandoc takes almost any words after
    `[label]:` for an address, run together: `[Methods]: patients were enrolled.` is a
    definition to it, and so is a reference list typed as `[1]: Smith J, Doe A. ...`, and
    it prints nothing of either. No real address has several words, so such a line is
    marked, and prints as it was written, as it did before `_blocks` took it for a
    definition. With one word after the colon, `[Note]: none.`, the line is a definition
    to both, and prints nothing.
  - *Beside a line pandoc does not take for blank, nothing is marked.* A line holding only
    a no-break or full-width space, or a form feed, separates blocks here and not for
    pandoc, and `_blocks` leaves the blocks on both sides of it unmarked. A definition under
    such a line is prose to pandoc, and prints; a note over one takes in the paragraph
    below. Either way what prints there carries no identifier, and is not compared.
  - *Each source file ends its notes.* `tag` judges a note at the end of a file by what
    follows it there, which is nothing. The build joined the files with blank lines alone, so
    a note ending one file took in the next file's first paragraph when that opened indented,
    and a co-author's edit to it was dropped. An empty div between the files, which puts
    nothing in the document, now ends the note. A comment did too, but its `-->` closed a
    `<!--` left open earlier in the file, and the rest of that file vanished. The next
    file's first paragraph, opening indented, is still code to pandoc, as it would be
    anywhere, and carries no identifier.
  - *A note straight under a heading or a fence is not checked.* A block that opens with a
    heading or a fence - code or a div - is left unmarked whole, as it always was, so a note
    written on the line under it, with no empty line between, is never asked whether it
    runs on. Under a line holding only a no-break space, the paragraph below goes into the
    footnote, and is not compared. An empty line before the note avoids it.
  - *Only a note left alone is read by itself.* Pandoc reads a note's text apart from the
    body. A note that runs on into the block below, or is marked for a line the rule
    refuses, is still read for raw content as a paragraph is: a `<!--`, `<pre>` or
    `\begin{...}` in its text leaves the paragraphs after it unmarked, and pandoc prints
    them. And a code fence wrapped onto a note's second line, left alone or not, is still
    paired with the next fence below, so what lies between goes unmarked, or a marker lands
    inside a real code block. Both are so on `main`.
  - *A note marked only for what is below it can become a definition.* A note over a blank
    line and then a line indented four columns would take that line in, so it is marked,
    and prints as text. Moved in Word to a place with a plain paragraph below it, it is a
    definition to the next build and prints nothing, while `import` reported the move as
    applied. The text stays in the source. Nothing yet refuses a change after which a
    paragraph `import` wrote would carry no identifier.
  - *A definition between two paragraphs is no section boundary.* It renders nothing in the
    body and pandoc reads it wherever it stands, so a move across it is applied: the
    paragraphs change places, and the definition stays where it was written. As untagged
    source text it first counted as a boundary, and such a move was refused as one past a
    heading, a table or a figure. `merge` asks `only_definitions_between`, by the test
    `_blocks` marks by, so a line in a definition's shape that is marked - in a shape pandoc
    could read otherwise, or a note that would run on into what is below - is a paragraph,
    not something between two. And a line pandoc does not take for blank - one holding only
    a no-break space - is a boundary wherever it stands between the two, above a definition
    or below one: pandoc prints it, and `_blocks` leaves whatever is beside it unmarked. A move
    across a definition can also carry a note marked for what is below it to where it
    becomes a definition (above).
- **A split is recognised by the new text beside it, and that is coarse.** An untagged
  paragraph whose text the document did not have when it was sent makes the tagged paragraph
  touching it a possible split. An edited heading is new text too, so when a heading and the
  paragraph under it are both edited in one round, that paragraph's rewording is refused.
  That is the price of refusing a split, and it does not refuse every one. The search for
  new text stops at the first untagged text the document already had. A table moved with
  its caption between the halves of a split, or a heading dragged there, puts that text
  first, so the paragraph is merged as its first half and the rest is gone from the source,
  as on main. Exit 1, because the caption or heading is reported out of place, but the
  merge is written. A tagged paragraph moved between the halves does the same, but only
  when Word keeps its bookmark; real Word drops it on a cut and paste, and the split is
  refused. A table, figure or equation the
  document as sent did not have counts as new text: a paragraph split around a pasted
  picture or a new equation was merged as its first half, because the search stopped at the
  first block that was not prose. One the document did have is looked past, as an empty line
  is: an equation cut from further down and pasted between the halves still matched itself,
  and the search stopped there too.
- **A join that lost its bookmark is recognised by resemblance, which is a judgement.** A
  join made by selecting across the boundary deletes the second paragraph's bookmark. When
  a paragraph changed and the one after it vanished, the import asks which the returned text
  resembles more: the paragraph as it was, or the paragraph followed by its neighbour. A tie
  counts as a join. Two counting rules came before this one and each was beaten in review by
  an ordinary edit. A join that also rewrote most of the second paragraph still reads as a
  rewording of the first and a deletion of the second: the first is merged with the combined
  text, and the second is reported deleted and left in place for the author to remove.
- **A paragraph that is not applied travels with the one before it.** Deleted in Word,
  moved into another file, absorbed by a join, or present twice, it has no position of its
  own in the returned document, so a reorder keeps it after the paragraph it followed in
  the source. That is a choice, not something the document says.
- **Token extents are trusted only where marking changed nothing.** The marked build must
  read exactly like the plain one, paragraph by paragraph. If a bookmark changes a
  rendering, that paragraph is refused rather than aligned on extents that describe
  different text, and it can never take a rewording, even far from the token. A binding
  inside inline code is not marked at all, since pandoc reads no bookmark there, and neither
  is a token after an odd run of backslashes, which would escape the bookmark's backtick:
  with no extent, its paragraph is refused the same way. If the marked build cannot be read
  at all, `import` carries on without it: for that run every reworded paragraph holding a
  binding or a citation is refused, and the run says why. Nothing in a broken build says
  which paragraph broke it, so none is singled out. Known cases of a changed rendering:
  super- or subscript around a token, `m^{{x}}^`, which the bookmark's markup breaks; a binding inside
  an autolink, which the bookmark breaks the same way; `@key [b][c]`, whose `[b]` is read
  here as a locator and is none to pandoc, being followed by `[`; and quotes that pandoc
  pairs differently around a bookmark. The no-break space pandoc puts after "et al." or
  "e.g." before a bookmark, where it puts a plain one before a citation, is not a change:
  one character for one, the extents still fit. A binding in an HTML comment is never
  marked, and `@a [-@b]`, `@key[p. 3]`, `@key [text](url)` and an `@` in a link's address,
  each once a token that marking broke, are read as pandoc reads them now. `[@key](url)` and
  `[@key]{.smallcaps}` no longer break marking, but a paragraph holding one still refuses
  every edit: the reading shows the link's text as `@key`, where Word shows the citation.
- **Only a sign glued to a value is a change to it.** "– 3.84", with a space, reads as
  punctuation and merges; so does a unit or a percent sign added after a value. Both change
  what the sentence claims, and neither is caught here; `check` sees the binding intact.
- **The annotated copy shows classification, not correctness.** Green means a number came
  from an artefact, not that the analysis behind it was right; the tiers describe provenance
  and nothing else. An SVG figure needs `rsvg-convert` for pandoc to place it in the contact
  sheet, so a raster sibling is preferred where one exists and the vector is skipped when it
  is not.
- **An interval is only checked in prose when it was emitted as one.** `em.interval()`
  publishes the estimate and both bounds together, verifies that the bounds bracket the
  estimate, and records which end each bound is — which is what lets G2 refuse
  `{{results.ror.ci_high}} to {{results.ror.ci_low}}`, a sentence in which every binding
  resolves, no literal appears, and the paper prints "3.84 (95% CI 7.02 to 2.10)". Three
  keys emitted separately with `value()` are still three unrelated numbers, and the order
  they are quoted in is unchecked. The order is judged per sentence, so a paper may quote
  one bound alone or two intervals in successive sentences without complaint.
- **A structured abstract cannot state its own signal threshold.** `methods_only` rules need
  a Methods heading, and an abstract's chain is `("Abstract",)`. Treating the whole abstract
  as Methods was considered and rejected: an abstract states results in the same block, and
  it is the highest-risk place in the paper for an unbound number. Bind the value, or use
  the project's own `conventions:`.
- **A reporting checklist's `where:` can only point at a manuscript heading.** RECORD's added
  items are answered in supplementary tables, appendices and registry records, so the items
  the extension exists for are the ones that report `checklist-location-unknown`. It is a
  warning, which is the only reason it is tolerable.
- **A Bonferroni-corrected or otherwise derived alpha is not a built-in convention.** Only
  the conventional thresholds are. A corrected threshold goes in the project's own
  `conventions:` with a justification, which is the right amount of ceremony for a value
  that depends on how many comparisons this particular paper made.
- **The linear-time tests measure time, so they see a quadratic only once it shows.** Each
  times a scan on eight times its input, taking each size's best of three in alternation,
  and fails at sixteen times the time (`check_linear` in `tests/conftest.py`). A scan whose
  quadratic part is under a seventh of its time on the smaller input passes, and so does
  n log n, which reads 10 to 14. A linear cost with a large constant is invisible to it: the
  per-atom window scans that took `check` to 30 s were linear, and only a budget caught them.
  Each of these tests used to rest on one timing per size (one on a best of three, one size
  after the other), or on a budget, and a busy runner decided one of them. A quadratic at C
  speed shows only at a size where it outweighs the per-item work, and one in Python fails
  quickly from a small size but takes minutes from a large one, so the size a test starts
  from is its sensitivity as well as its cost. Paragraph tagging is checked twice, from 10
  blocks and from 1,000. They are tripwires for the scans that went quadratic before, not a
  proof that nothing else does.

## Still open

- Who reviews additions to the per-project convention allowlist, and whether entries need
  a written justification. The schema already requires a `why`; nothing enforces review.
- Cross-platform hook portability. Only Windows is available for testing, so CI runs
  Ubuntu and macOS.
- Zotero group library support, and behaviour when a citation key is pinned in one library
  and absent from another.

Resolved 2026-08-03: the pre-analysis design gate **warns rather than blocks**, so
exploratory work stays possible.

Resolved 2026-09-24: after a revision, **a later complete round supersedes the outdated
rounds before it**, chosen over requiring every round to be re-read, over superseding only
across a journal's revision, and over leaving it as it was. See "Review panels" above.
