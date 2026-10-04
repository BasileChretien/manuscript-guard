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
- **Word does not carry a paragraph's identifier when it cuts the paragraph** (Word 365,
  driven over COM on the example's build, 2026-09-24). The identifier is an empty bookmark,
  and Word leaves an empty bookmark where it stood. With Track Changes on, it stays in the
  moved-from copy; without, it moves onto the next paragraph. That is the first paragraph
  of what it cuts: the bookmarks of the paragraphs after it go with them (2026-09-28).
  Text pasted or typed at the
  start of a paragraph, Enter included, goes in behind that paragraph's bookmark. And
  pandoc's reference document sets `w:doNotTrackMoves`, so a move made with Track Changes on
  came back as a deletion and an unrelated insertion. See "A move, the way Word makes one".
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
    panel/         # model providers reading the review panel; no gate imports it
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
  AGENTS.md             # the rules of the project, for any agent working in it
```

`AGENTS.md` is there because the skills and the hooks reach an agent only where they were
installed, and several agent tools read that one file at a project's root on their own. It
holds what the guarantee rests on, on one short page: machine-written files are not edited,
`check` runs before a build, and nobody but `check` decides that the manuscript is clean. It
is worded to hold in any project at any time, because it is written once: a finding is never
typed, though a convention, a pointer, a label or a name is; `check` decides for the stage
the project declares; and for how to install the skills it points to the README without
saying what the README holds for which tool. Where it does not hold, Known gaps says so. It
names no agent tool. Like every file of the scaffold it is never written over an existing
one; where a repository already has an `AGENTS.md` that does not mention the toolkit, `init`
prints the rules to add, because an agent there would otherwise read rules that say nothing
of `results/`. It is advice to the reader and enforces nothing: the gates do that.

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
| G14 | Abbreviations | never: it warns when one is used before it is defined, defined twice, defined for nothing or never defined |

Plus one code that belongs to no gate: `gate-errored`, raised when a gate itself throws. It
is in no stage's deferral list and so fails everywhere, because a checker that could not
check is not a pass. Where what the gate threw is the project's own error about a file it
reads, a review record that is not UTF-8 for one, the finding carries that sentence, which
names the file, and does not call it a bug.

And one for the manuscript itself: `manuscript-unreadable`, for a manuscript file whose text
cannot be had, because it is not UTF-8 or the system will not open it. Each gate that reads
the manuscript stops at such a file, so it is reported once for each file, at the file and
the line, with the gates that did not run. The other gates report as usual. It fails at
every stage too. Outside `check`, a command that reads the manuscript's text says the same
sentence and exits 2. Of those, the dry run of a review panel is the one that does not: it
decodes the files itself, names the file and exits 2, with neither the byte and the line nor
the encoding. `review` reads only the bytes, for the digest, and the note after an edit reads
the text with the bytes it cannot decode replaced; neither says anything of the encoding.

And two that `check` takes from the build, under `BUILD`, without making a document. One is
the shapes the build would refuse, read from the sources. The other is TeX in the text that
the Word writer would leave out, `tex-in-the-text`. For that one `check` runs pandoc, once
for the paper and once for its supplement, on the text the build would hand it, and reports
what the build refuses, in the build's sentence, at the file and the line. It fails from
`drafting` on, and the build's warning of a layout command, `tex-does-nothing`, comes with
it. Like the reading of a PDF, this finding depends on a program outside the package, and
on its version, as the build does: a pandoc that reads a line otherwise than the one CI
pins reports otherwise, in `check` and in the build alike. Where pandoc is not on PATH,
`check` does not judge TeX in the text. Its exit code is that of a pass, and it says so
once, in a note: `tex-not-judged`, whose severity is `info` and whose code is its own, with
the count `documents_read_for_tex` at 0. Every other gate runs as usual. `check` gives
pandoc ten seconds for each document and then stops it: a document pandoc has not read by
then, one it cannot read, and a pandoc that cannot be run are each that same note, for that
document.

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

**A line of dashes opens no block.** Below the front matter, pandoc may read a line of
dashes with a line directly under it as the start of YAML metadata, when the lines under it
are a mapping, or of a table, and prints no heading from either. YAML there is merged over
the build's header with the later value winning, so a `title:` in it replaced paper.yaml's
on the title page; and the gates, reading prose, took the closing rule for a setext
underline, so `note: |` over an indented `Methods`, or `Methods` alone in a one-cell table,
under `## Results` headed the paragraph after, and `p < 0.001` in it passed as the alpha
chosen in advance. Both of pandoc's readers were modelled in the heading scan first, along
with what the build's bookmarks do to them, and two rounds of review each found the model
and the build printing different headings, the second round's worst caused by the first
round's fix. So the shape is refused instead (`rule-opens-a-block`), by `check` and by the
build.

The refusal first exempted the underline of a setext heading, and that exemption was a model
of its own. Four reviews each found titles the heading scan took and pandoc did not: a div's
fence, an HTML tag, LaTeX, a table's row, indented code, and a line continuing a paragraph,
a quotation or a list item (the first); a comment on the line above, which pandoc reads as
no break (the second); a table placeholder with spaces in its braces or after other text
(the third); and a comment after the underline, a comment whose last line looks like a
heading, a listing pandoc does not make, and an `===` underline pandoc does not read above
the title (the fourth, with four false passes through `check` and the build). The fourth
also found the rule's other side open: `# Methods` or a quotation over `---` and a blank
line is a setext heading to pandoc, made before the `#` heading or the quotation. So a line
of dashes now passes only between blank lines, where pandoc reads nothing but a thematic
break, and a heading is written with `#`. Nothing in `example/`, the scaffold or the skills
underlines a heading with dashes; `===` has no dashes to misread and is untouched. A line in
code, a comment or the front matter is not read, and a comment that closes on the line is
taken off in front of it, as pandoc reads on from its `-->`. The fifth review found pandoc
starting a block partway along a line, behind an HTML tag or comment, a TeX command, or a
list, definition or footnote marker, and reading the dashes after it as YAML; dashes ending
a line that opens with any run of such markers, block-level HTML tags (pandoc's list, and
the tags it takes for a block or inline as it finds them), comments, processing
instructions, or TeX commands with their groups, are refused wherever they stand, outside a
quotation, and so is the same after a comment that closes on the line. Three dashes at
least: two are an en dash, and a list item that is one opens nothing. Inline markup,
`m<sup>2</sup> ---` or `[drug]{.smallcaps} --`, starts no block and is prose (the sixth and
seventh reviews). The eighth found four more of pandoc's block tags (`applet`, `area`,
`frameset`, `isindex`), and the pattern reading one line more ways than one: a roman
numeral that was a letter too, a comment running on across later ones, a TeX command's
name stopping at any letter, and an optional argument that was a footnote's marker, so a
line of a few hundred markers took minutes. Each now reads a line one way, and the dashes
are split off from the end of the line before the rest is matched. The eighth round's fix
took every `[^` after a command for a footnote's marker, and the ninth found pandoc taking
`\newpage[^1]` whole, the YAML under it read. A bracket is a command's argument before its
groups, colon or not: `\newpage[^1]: ---` is the command and then text, no footnote's
marker. After a group a bracket is text, and `\vspace{1em}[^x] ---` opens no block; the
review of #65's fix-only round found it refused, and it passes now.

**The build asks pandoc.** Every shape in those refusals was found by a review, a round at a
time, and the fifth still found five that put another title on the title page, and shapes
no refusal of a single file can see: a comment the heading scan misreads, and a comment or
a fence carried from one file into the next. So before it writes the document, the build
reads it with pandoc (`build/reading.py`) and refuses (`MisreadError`, exit 1) when the
metadata of the whole text differs from that of the build's header alone, or when the
headings pandoc makes differ from those the gates read in the sources. Nothing there lists
shapes, so most shapes nobody has found yet are caught too. Each heading the gates read is
paired with the one at the same index in the same file with its values put in, and
compared by that title, so `{{results.dose}}mg` reads as `50mg`; a file whose headings
change in number or level when its values go in is refused (see Known gaps for values
that move one). A placeholder used to match any text instead, and the eighth review
found a title that was only a placeholder matching whatever heading pandoc made at its
level, so two misreads that cancelled passed. The titles are read by pandoc as well, each a
numbered paragraph of its own behind a lead made new each build: compared as written,
`$\beta_{1}$`, `HbA~1c~`, `&amp;`, a comment or a footnote in a title split into other words
than pandoc's, and the sixth review found each refused. One pandoc makes no paragraph of,
block HTML in it, is compared in its own words, where the seventh review found it switching
the check off for every heading of the document. Raw markup and footnotes print no words in
a heading. A heading in a quotation, a note or a figure is left out on both sides, the
gates reading none there by design; one in a list, a definition or a table is the
document's, and the seventh round's leaving those out too passed `1. # Results` with a
claim under it, which the gates read under the heading before (the eighth). Such a heading
matches none the gates read, and always refuses: the ninth review found `- # Methods`
standing in for a `# Methods` the gates misread straight under a line of text, the claim
between passing under the wrong heading. The header's metadata is read on its own: read
with the titles and the definitions they refer to, a footnote's definition holding a YAML
block set a title there too, and the whole text matched it (the eighth). The definitions
are copied from the text the gates do not take for code or a comment (`scannable`), and
when the header or the titles cannot be read on their own while the document can, the
build refuses (see Known gaps for a definition in a `<pre>`): the
ninth review found a commented-out footnote holding broken YAML failing that run, which
switched the check off. The lists are aligned, so a refusal names the heading, with the
file and line of one the gates read. Pandoc's reading is walked without recursion, and a
document nested too deep for Python's JSON reader, two thousand divs, is refused.

It costs two more runs of pandoc's reader a document, three with listings, and one on the
header, kept for the next document with the same header. It guards the document, not
`check`: a source the build refuses can still pass `check`, and a number a misread hides
from G2 without touching
metadata, headings or listings is not compared. A refused build removes the document the last one
left in build/, which is not this source's, so that it is not sent or packed; a refused
supplement fails `build` and `submit` like the paper, and `submit --document` refuses a pack
missing either, taking the supplement beside the document, or else the one in build/. It
refuses a document inside build/submission/ too, which the new pack replaces: the ninth
review found `--document build/submission/manuscript.docx` deleted before it was copied. Two
builds go without asking: `import`'s, since the document it rebuilds has already been sent,
and refusing there stranded it with the co-author holding it; and the annotated copy, marked
up for the author to read, whose marks the annotator has pandoc check as it makes them
(#76).

**The header comes from `paper.yaml`, and a manuscript's front matter prints nothing.** The
build strips every source file's YAML block and writes a header of its own with the title,
short title and keywords from `paper.yaml`. A `title:` in the manuscript is compared with
that one and a disagreement warned about (`two-titles`): by `check` at every stage, and by
`build` and `submit` before the document is made. An `abstract:` there is refused,
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
install. `pdftotext` is asked for UTF-8 and read as UTF-8 whatever the locale, and a
`pdftotext` that fails or gives nothing leaves the PDF to `pypdf`.

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
at the column boundary and each column into topic, number and text sub-columns. The page is
asked for in UTF-8 and decoded strictly: one `pdftotext` cannot give in UTF-8 is refused,
not transcribed with a letter replaced.

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

A finding's line is counted in the file as read. The phrase and attribution rules match in a
copy with the comments, the listings and the front matter's machinery blanked, line ends
included, and an offset is the same in both. Counted in the copy, the line fell short by
every line blanked above it: a phrase under a four-line comment was reported three lines up,
on the comment. And the line is the one the matched words begin on, not the match: the rule
for a chat assistant's opening word reads from the start of a line through any blank lines,
and its finding was put on the blank line above the paragraph.

**Vague attribution gets the one check an encyclopedia cannot use.** "Studies have shown" is
reported only when no citation sits within 240 characters, because in a manuscript the fix
is a reference rather than a rewrite.

## Abbreviations are checked against the manuscript, not against a style guide

G14 is the first check on the language itself, and it is built on one distinction. Whether
"ROR" has to be defined is a question about a journal: one house style expands "CI" and
another lets it stand. Whether "ROR" *was* defined, where, how many times, and whether
anything used it afterwards are questions about the manuscript, and they have the same
answers in any field. The gate asks only the second kind:

- `abbreviation-used-before-defined`: the short form appears above the sentence that
  defines it;
- `abbreviation-redefined`: it is defined a second time, or as two different things;
- `abbreviation-unused`: it is defined and nothing uses it afterwards;
- `abbreviation-undefined`: it is used and never defined.

**A definition is read by its shape.** A long form with the short form in brackets after
it, or the short form with the long form in brackets, where the letters of the short form
can be found in order in the long one and the first of them begins a word. That is Schwartz
and Hearst's rule (Pac Symp Biocomput 2003;8:451-62), written out here in thirty lines
because a gate that runs in CI should not take a dependency for them. The short form may
also stand in square brackets, "hazard ratio [HR]", which is how a journal writes a
definition inside a parenthesis. The short form in a definition may be anything with two
capitals, or one that is not the capital of a word (`mL`), or a capital and a digit. A
plural defines its singular: `RORs` defines `ROR`, and `mAbs` after "monoclonal antibodies"
defines `mAb`.

**An abbreviation nobody defined is read by its capitals.** A word met with no definition
is taken for one only when two capitals stand side by side, which keeps `McNemar`,
`DeLong` and `PhD` out of the report. Three things with two capitals together are not
abbreviations and are left alone. A numeral, `II` to `XXXIX`. A registration or accession
number, letters and then five digits or more: `NCT01234567`. And a chemical formula: a
word that reads from end to end as element symbols and their counts, with a count
somewhere. The count is what tells the two apart. `CO2`, `H2SO4` and `NaHCO3` are formulas;
`CO`, `CI` and `HCV` spell elements too and are abbreviations, and so, for the gate, are
`HCl` and `NaOH`, because nothing distinguishes them from `PCa` (prostate cancer) and `SCr`
(serum creatinine), which the first version of this rule let through as formulas. A count
is from two to twelve: nobody writes a count of one, which keeps `HSV1` in the report, and
none runs to fifty, which keeps `IC50`. A count typeset as pandoc's subscript, `CO~2~`, or
in subscript digits, is read as the count it is.

**A hyphenated word is one abbreviation where it reads as one.** `SARS-CoV-2` is read
whole when it is defined or known, and so is a name that holds an ordinary word:
`RNA-seq`, `non-HDL-C`. Where nothing in it is defined or known, it is reported whole,
under the name its definition would give it: `LC-MS` and not `LC` and `MS`, `KEYNOTE-189`
and not `KEYNOTE`. An ordinary word joined on is then no part of it: `ROR-based` is `ROR`.
The defined or known name is looked for first. The second review found the order reversed:
the word was split at `seq` before `RNA-seq` was looked for, and its definition was
reported as unused. A name that opens with an ordinary word is looked for with that word's
capital lowered as well, because it takes one at the start of a sentence: `Non-HDL-C` is
`non-HDL-C`. The capitals of the name itself are never folded, so `Rna-seq` is not
`RNA-seq`.

**Three texts are read apart, because each is read apart.** The abstract is indexed and read
without the paper, so it defines what it uses. The main text does not inherit from the
abstract, and says so when that is the reason for a finding. The supplement is read after
the paper, so it inherits the main text's definitions and nothing else. Files are read in
the order the build prints them, and a file that opens without a heading continues the
section the one before it ended in.

**What is not a sentence is not read.** Listings, comments, bindings, citation keys and
link targets go with `mask`, and inline code, equations, image captions, front matter and
headings go after them: a heading in capitals is not an abbreviation. A reference list is
not read at all. In a contributions, acknowledgements, funding or competing-interests
section, capitals are people and institutions, so nothing there is reported as undefined,
and a funder named once with its acronym is not reported as unused. Those sections are
found by a word anywhere in their title, since each publisher words the heading its own
way: "CRediT authorship contribution statement", "Role of the funding source".

**What may stand undefined is data.** `data/abbreviations.yaml` holds a short list of what
general English reads as a word or a name, `DNA`, `UK`, `DOI`, and a few unit symbols with
two capitals together, `MHz`, `GPa`. It is short on purpose. A long list would decide for
every field at once what its readers know, and an entry with a second meaning hides that
meaning: `AD`, `BC` and `PM` were in the first version as eras and times of day, and the
first review took them out, because in clinical prose they are Alzheimer's disease, breast
cancer and particulate matter. To it are added the names
G2 already reads as names (`terms.yaml` and the project's `terms:`), the reporting
guidelines the toolkit has a recipe for, the ones the project declares, and whatever the
project lists under `language: known_abbreviations:` in `paper.yaml`. A listed abbreviation
that the manuscript defines anyway is still held to that definition.

**Every finding is a warning, at every stage.** The reading of a definition is good and not
exact, and a name in capitals is not an abbreviation. The first plan for this gate had an
undefined abbreviation fail a submission build. Run on the realistic manuscript kept in
`tests/test_language.py` it gives 22 findings, of which two are names: a trial and a
statistics package. The first review's probes in chemistry and physics added formulas
and unit symbols to what it got wrong, and the rules for those are a reading too. A check that is wrong that often may advise; it may not stop a build.

The worked example found its own slip the first time the gate ran: the Introduction writes
"(ROR ...)" and nothing defines ROR. It is left as it is, because the example's review
records are tied to the text they read, so `check` on the example prints that one warning.
`CI` is listed in the example's `paper.yaml` to show the setting.

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

**A remit can be read by several readers.** One reviewer had one record a round, so a remit
could be read once. A panel read by models from several providers has several readings of
each remit, and a co-author may read a remit a model also read. Each reading is a record of
its own, `review/round-N/<reviewer>.<reader>.yaml`, beside the plain `<reviewer>.yaml`; a
reviewer's id cannot hold a dot, so the first dot ends it. The record says the same `reader`
inside. Nothing is merged into one file, because a record several writers append to is a
record that can be re-stamped.

**The panel says who reads, and is held to it.** A reviewer's entry lists the `readers`
asked to read the remit, and G11 wants a reading from every one of them: `reading-missing`
leaves the round unfinished. With every model reading every remit, one provider failing
must not leave a round that looks complete, and this is what lets the readings that did
arrive be filed: the round is visibly incomplete until the missing reader reports or is
taken out of the panel, which is a decision somebody made and the file records. The author
chose this over two alternatives. Counting a remit as read once anybody had read it passes
a round two of three models answered. Filing nothing unless every call succeeded throws
away replies already paid for. A panel that names no readers needs one reading, the
reviewer's plain record, which is how every round written before this is read; the
example's two rounds give the same findings as they did, which is none. What is new for
them is a count of readings in the report and the list of who read what in
`manuscript-guard review`.

**And only the readers the panel names are read.** A file `<reviewer>.<reader>.yaml` is a
reading if the panel lists that reader for that reviewer, and nothing else beside a record
is one. `review --record <reviewer> --reading <reader>` lists the reader when it files the
reading, the way `--record` puts a reviewer on the panel. The first two versions of this
decided from a file's contents whether it was a reading, and two review rounds each found
one that dropped out of a round without a failure. A reading whose author answered a
finding with `resolution: Fixed: it now says reporting`, which is not YAML, was taken for a
note: a warning, and its other major finding stopped binding. With that fixed by looking
for a `reader:` line, one saved again in UTF-16 was taken for a note, and so was one with
the key quoted. In the other direction, a note in another code page that the gate had no
business opening took it down. The author chose to stop guessing over two alternatives:
patching each shape as it was found, and treating every such file as a reading, which
would have failed a submission over a copy kept in the round. So:

- A file under a name the panel asks for is that reader's reading, whatever it holds. It
  must parse (`reading-unreadable` if not, a failure at every stage like any malformed
  record), fit the schema, and say inside the reader, the reviewer and the round its place
  says (`reading-misfiled`). Until it does, the round is unfinished.
- Any other file beside a record is not opened. It is reported as `reading-unnamed`, a
  warning at every stage, with how to make it count. `biostatistician.old.yaml`, a note in
  UTF-16, a folder: none can fail a submission or take the gate down, as none could before
  readings had names.
- The reviewer's plain record is the reading nobody named, and answers for no named reader
  whatever it says inside.

The cost is the one case the warning is for: a reading put beside a record by hand, with
its reader not in the panel, is not counted until somebody adds the reader.

**A reader is known by the name that names its file.** A reader's name becomes part of a
file name with its letters, digits and the marks that belong to them kept, in any script,
lower-cased and composed, and every run of anything else as one hyphen. That form is how
the gate recognises a reader, so the panel's `Dr. Tanaka` and a reading filed as
`Dr Tanaka` are one reader; matched letter for letter, the gate asked for a file that
existed and `review --record` refused to write it. The marks are kept because in scripts
that write a vowel as a mark on its consonant two names can differ in nothing else, and
with them dropped Reena and Raina were one file. The name is composed because some file
systems store an accented letter as the letter and its mark, and the same reader has to be
the same file wherever the project is checked out. Two readers of one remit whose names
still make one file name are `duplicate-reader`: one file cannot hold two readings. A name
with no letter or digit names no file, and is refused where it is typed and reported where
a panel holds one.

**Any reader can raise a finding, and nobody's reading answers another's.** Every reading
is judged as a record always was: stale when a file it read changes, counted for coverage,
and each unanswered major finding blocks a submission, with the reader who raised it named.
The gate does not match similar findings across readers. Two models saying the same thing
in different words are two findings to answer, and deciding they are one is a judgement the
author makes in the resolution.

**The strictest verdict is reported and decides nothing.** `manuscript-guard review` lists
who read each remit, what each concluded and the round's strictest verdict. G11 has never
decided anything on a verdict, and still does not: a record cannot be re-stamped, so a
verdict could be cleared only by a further round, and what an author can act on is a
finding.

**What a model's reading may keep.** A record may carry `provenance`: the provider, the
model as asked for and as the provider named it, the host, the SHA-256 of the request body,
the provider's response identifier, how the reply ended, the token counts and the version
of this tool. The schema refuses any other field there, so nothing has a place to put a
key, a header or the prompt's text. What goes into the fields the provider words (its name
for the model, its response identifier, its reason for stopping) is for whatever writes the
record to clean. `rejection_tests` records what the reader decided would have to be true
to reject, and what the manuscript showed. The gate reads neither.

The worked example carries a real two-round panel. Round one found that the paper had no
case definition, no mention of duplicate records, and no contingency table for a result that
was a single ratio; all three were fixed, and the manuscript is better for it. Round two,
blinded and differently composed, found the remaining soft spots. Two findings are recorded
as deliberate overrides rather than fixed, because the honest answer was that the synthetic
data do not support what the reviewer wanted.

## A panel read by several providers

The panel existed only as a skill for one agent. A scientist without that agent could not
run it, and a panel drawn from one model shares that model's blind spots. So the reviewers'
remits can be read by models from several providers, listed once in `paper.yaml`:

```yaml
review:
  models: [openai/<model>, mistral/<model>, moonshot/<model>]
```

**This is a layer beside the gates, not a gate.** `src/manuscript_guard/panel/` holds every
provider call, and nothing under `gates/` imports it; a test reads the imports. The gates
still run in CI with no network and no model. A model files a review record, and G11 reads
records as it always has. A model does not decide whether the manuscript is clean.

**One client, no new dependency.** OpenAI, Mistral, Moonshot (Kimi), DeepSeek, OpenRouter,
Google's Gemini endpoint and a local Ollama all speak the chat API OpenAI defined, and
Anthropic speaks its own. Two request shapes on `urllib` cover all of them, so a preset is
four facts: the base URL, the name of the variable holding the key, the shape, and how the
vendor spells an output cap. Each was read from the vendor's documentation on 2026-10-02 and
a test holds the table. No preset names a model: model names change faster than a release,
and the author supplies them. A provider that is not built in is added under
`review.providers` by its URL. A built-in name cannot be pointed elsewhere, and a provider
that is not built in cannot name a built-in provider's key variable as its own: either
would let a `paper.yaml` somebody else wrote send the reader's key to a host of its
choosing. The address must be one host, a port if it needs one, and a path, in plain
characters; `http://[::1].evil.example` and `http://@localhost` are refused, since what
decides whether a call stays on this machine is the host. The host itself is letters,
digits, dots and hyphens, or a bracketed address, with nothing encoded: urllib decodes a
percent-encoded host before it connects, so `api.openai.com%2e%65%76%69%6c.example` was
shown to the author as written and reached `api.openai.com.evil.example`. The host the
statement names has to be the host that is connected to, and that is now checked as such:
the host shown is compared with the host urllib derives from the address, and no `%` is
taken in it. Listing the shapes that mislead missed one twice; the second was a `%` after
an address in brackets, which reads as a zone id. A host that ends in a number is an
address and must be four numbers with dots, since `2130706433` and `0x7f.1` are each read
by the resolver as an address the text does not show.

**Keys.** A key is read from its environment variable when a call is made and goes into one
request header. It is not in the request body, so the body can be printed and digested. It
is not written to a file, a record or a message: `review --providers` says only whether each
variable is set, and a rejected key gets a message of our own. Anything printed that
somebody else wrote, a provider's error or an exception's text, has every run of four or
more of the key's characters taken out first, because a provider's message for a bad key
can quote its first and last few; the review of the first version found the whole key
printed when it held a line break, inside the message `http.client` gives for a header it
will not send. A key holding a space, a line break or a character outside ASCII is now
refused by its variable's name before it reaches a header, and what an exception says
about a request it would not build is never repeated. `key_env` must look like a
variable's name, upper case, so that a key pasted there is refused rather than committed.
Keys go over https, or to this machine. A redirect is not followed: it would carry the key
and the manuscript to a host nobody agreed to. A request to this machine does not go
through the proxy the environment names, which urllib would otherwise have handed it to.

**The manuscript is unpublished, and sending it to a third party is the author's
decision.** The toolkit cannot know what a provider keeps, for how long, or whether it
trains on it; that is in each provider's terms, and they differ and change. What it can do
is say what would leave the machine before anything does. `review --run --dry-run` builds
every request exactly as a run would, prints which files go to which host and how many
calls that is, writes the bodies under `build/` with a readable copy of their text, and
opens no connection. A model that Ollama runs on this machine is the option that sends
nothing anywhere. The statement used to say "this machine; nothing leaves it" of any
address on this machine, and Ollama's server there also serves Ollama's cloud models, whose
requests it sends to Ollama's servers. A model named as Ollama names those, `-cloud` or
`:cloud`, is now said to leave the machine, and any other model on this machine is said to
stay there unless the server there passes it on, which the address cannot show.

**What a reviewer is sent is a fixed list**: the paper's title, keywords, journal and
guideline from `paper.yaml`; the journal profile and the reporting checklist where the
project has them; every manuscript file; and that reviewer's own role, remit and reason.
Nothing else is sent. That list is how the second panel stays blinded when models run it.
The earlier rounds' records, the other panels and the response to a journal's reviewers are
not on it, so no request can carry them, and a test plants a marker in each and looks. For
the same reason `authors.yaml`, `results/` and the literature sources stay where they are.
`results/` and the ledger are read, for the values the bindings print, and only those
printed values reach a request.

Three entries of that list are named in `paper.yaml`, and the first version joined each
name into a path without looking at where it led. `reporting_guideline:
[../../review/round-1/biostatistician]` put round one's record in every round-two request,
`target_journal: ../../authors` sent `authors.yaml` as the journal profile, and
`paths: {manuscript: .}` made the notes beside the review and the response to the reviewers
into manuscript files. A journal or guideline now has to be a name, and the file it
resolves to, with links followed, has to sit in the project's `profiles/` or the shipped
ones and not under `review/` or `revision/`, which a `profiles/` directory that is itself
a link could otherwise lead to. The manuscript directory may not take in `review/` or
`revision/`, nor sit inside
them, and a manuscript file that is a link to somewhere outside it is refused. A
`paper.yaml` its schema refuses is not planned from at all.

The manuscript is sent as the build prints it. Each binding is replaced by its value and
each table rendered, because a reviewer shown `{{results.ror.point}}` cannot check a
number. Each file's YAML header and every HTML comment are left out, as the build leaves
them out: a comment is where authors are told to keep their notes, and "the round-one
statistician asked for this" is not something to hand a blinded reviewer. The files go in
the order the build prints them, `main.md` first and the supplement last.

**Agreeableness is the failure to design against.** A panel of personas that all approve
has told the author nothing. Each reviewer is told to decide first what would have to be
true, within its remit, for it to recommend rejection, and to check each against the text;
the reply must carry those tests, so a reading that attacked nothing shows.

**A reply is untrusted input.** It is accepted when it is one JSON object that fits the
reply schema, bare or in a single code fence, and refused otherwise. Nothing is repaired:
prose around the object is not trimmed, a truncated object is not closed, a verdict outside
the vocabulary is not mapped to the nearest one. A reply cut short by a token limit is
refused even if it parses, and so is one the provider marks as a refusal. The reply schema
holds only what a reader can know. Who read, when, and which version are filled in by the
tool, and a finding's `resolution` is the author's to write, so a reply carrying one is
refused: it would file a major finding already answered. One thing is read as what it
plainly says: a finding's `where` may be left out, a model that leaves a key out often
writes `null` for it, and null there is taken as absent. No other key may be null, prose
made only of white space is not prose, and a character that could not be written to a
record (a NUL, half of a surrogate pair) refuses the reply while it can still be refused.

**Nothing is asked twice without a reason.** A rate limit or an overloaded server is
retried twice, because no reply was produced. A timeout is not: the provider may have run
the request and billed for it.

**By default every model reads every remit**, because the point of several models is that
one's blind spot is another's finding; `--one-each` deals one model to each reviewer in
turn, for a third of the cost with three models. With no panel file, rounds one and two
have a starter panel that assumes no field, so a first run needs only the list of models.
It is shown before anything is sent and left in the panel file to be edited. A second
starter panel shares nobody with the first.

**Sending needs a yes, and the yes is asked after the statement.** `review --run` prints
what the dry run prints, then asks, and takes only the word `yes`. Where nobody is there to
ask, in a script or under an agent, it sends nothing unless `--yes` was given. Everything
that can be known beforehand is checked before the question: a key that is not set, or is
set to something that is not a key, stops the run with nothing sent to any provider, because
half a panel sent for a reason that could have been said in advance is a manuscript already
disclosed and a round to finish. So does a record that could not be filed whatever the
reply: a record lists the files that were read, its schema takes no `..` in a file's name,
and with a manuscript file called `appendix..v2.md` every call was made and every reply
refused. The tool's own part of each record is now tried against the schema first. When
every reading of the round is on file there is nothing to send, and no yes is needed to
send nothing. Ctrl+C at the question is a no.

**A run can be stopped.** Ctrl+C after the yes stops the sending: no call is begun after
it. A call already made cannot be recalled, so it is waited for and its reply filed, and
the command says how many calls were not sent. The first version handed each provider
its calls as one task and waited for all of them, so an author who changed their mind
could only kill the process.

**The panel is written before the first call.** It names every reader that is about to be
asked, so a run that is interrupted, or in which a provider fails, leaves a round G11 sees
as incomplete: each reading that did not arrive is a `reading-missing`. A round with no
panel gets the starter panel the author was shown; a panel that exists keeps every word of
its own and gains the readers. Running the command again asks only for the readings that
are missing, and the ones on file are not asked for, paid for or replaced a second time.
If the panel no longer names a reviewer the statement named, because it was edited while
the question waited, nothing is sent.

**The command does not call a round read while its panel waits for a reader.** A run asks
the models listed now. The panel may name others: a model taken out of `review.models`
after a provider failed, or one that `--one-each` dealt to another reviewer this time.
The first version said every reading of the round was on file, or that two of two were
filed, and exited 0, with G11 still reporting `reading-missing`. It now lists the readers
the panel is waiting for, says how each is released, and exits 1.

**A reading is filed whole or not at all.** A reply becomes a record only after it came
back finished, parsed, fitted the reply schema, and the record built from it fitted the
review schema and read back from YAML as it was written. That last check is made by
making the trip: YAML writes U+0085 as it is and reads it back as a line break, so a
finding reached its record with a word boundary the model did not write, and a reply
that does not survive is refused rather than filed changed. The record is written under
a temporary name and linked into place. A link
refuses a name that is taken, where a move replaces what is there: somebody can file a
record by hand between the look for one and the move, and a record is not re-stamped, by a
run any more than by `review --record`. Every word of the review in the record is the
model's. The tool adds who read, when, the digests of what was sent, and the numbering of
the findings; it writes no `resolution`.

**What the record says of the call** is under `provenance`: the provider, the model asked
for, the host, the SHA-256 of the request body, the token counts, and the version of this
tool. The request body never holds the key, so its digest can be compared with the dry
run's. Two more fields are the provider's own words, the response id and the name it gives
the model it served, and they go into a file that is committed. Each is filed only when it
is one printable line of at most 200 characters with no four characters of a key in a row;
otherwise the record does without it. A review that holds twelve characters of a key in a
row, or the whole of a key of eight to twelve, is not filed at all. A model is never sent the key and cannot repeat it, but a gateway
between could put it in a reply, and the rule is that no key reaches a file.

**A reply that is refused is kept to read and counted nowhere.** It goes to
`review/round-N/refused/` as text, with a line saying why and that it is not a review
record. No gate looks there. The author paid for the reply and may want to see what the
model said; it cannot become a record, and it goes when that reading is filed. The key, or
any four characters of it in a row, is taken out first.

**One provider failing does not undo the others.** Providers are asked side by side, each
one call at a time. The readings that arrive are filed, the command exits 1, and it says
how many of how many were filed and that the round is incomplete.

**Two writers of one panel take turns.** A run writes the panel, and so does every
`review --record --reading`, which an agent may call for six readers at once. Each read the
panel, added its reader and wrote it back, and six at once left a panel naming two, three
or five of the six, with the other readings unread by the gate and only a warning to say
so. A panel is now held, through a lock file beside it made by exclusive create, while it
is read and written. A writer waits up to thirty seconds for it and then refuses in words
that name the file; a lock older than two minutes is taken for one its writer left behind.
A folder that cannot be written to makes no lock and leaves none to wait for: that is
refused after two seconds, where the first version tried again without a pause and
without an end. `review --record` reads its own round's panel only while it holds that
panel's lock. One version asked whether a reviewer was on the panel before asking for
the lock, so that a refusal would leave no folder behind; a writer rewriting the panel
empties the file first, and a reading for a reviewer who was on it was refused, about
three times in a thousand calls made at once. That question is now asked early only
where there was no `review/` when it looked. A writer can still make `review/` and a
panel between that look and the read. A refusal from it is then the one the call would
have had if it had come first, so it is never a wrong one; a panel that names the
reviewer lets the call go on to the lock.
The record itself is written by exclusive create, so two calls for one reader cannot both
succeed.

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
  failure, or where the project cannot be read for the check to run.

That last one carries a specific lesson. It matches the **whole command string**, with no
permission-rule prefix filter, because `cd example && manuscript-guard submit` and
`FOO=1 manuscript-guard submit` both defeat a prefix rule — which is precisely how a
submission build slipped past the equivalent guard in the predecessor project. The cost is
that the hook fires on every shell command, so it has its own console script
(`manuscript-guard-hook`) that imports nothing heavy until it knows it has work: 152 ms for
the no-op path against roughly 400 ms through the full CLI.

It is registered for the three tools through which Claude Code runs a shell command: `Bash`,
`PowerShell` and `Monitor`. Each sends the command in `tool_input.command`, and the guard
reads the command, not the tool's name. It was registered for `Bash` alone until 2026-10-02,
and a matcher made of letters and `|` is a list of exact tool names, for Claude Code and for
Codex alike. On Windows Claude Code makes PowerShell an agent's first shell, and by its
documentation has no Bash tool at all where Git Bash is absent, so there the guard never ran.
Seen in a session with both tools (Claude Code 2.1.286): in a copy of the example with its
reviews deleted, `echo 'cp build/manuscript.docx elsewhere'` through the Bash tool was
refused, and `Write-Output 'Copy-Item build\manuscript.docx elsewhere'` through the
PowerShell tool was not. With the three names registered it is refused too, as a session
started after the plugin's update showed on 2026-10-03 (Known gaps has what was seen).
`tests/test_plugin.py` holds the matcher to the three names. The
markers took the PowerShell and Windows spellings of the verbs they already had at the same
time: `Compress-Archive`, `Send-MailMessage`, `Invoke-WebRequest` and its alias `iwr`,
`Invoke-RestMethod`, `Start-BitsTransfer`, `robocopy` and `xcopy`. `Copy-Item` and
`Move-Item` were held before, since `copy` and `move` stand in them as whole words.

**The command is held to the project at the agent's folder, or to the one it names.**
Recognising `cd example && manuscript-guard submit` is half of catching it. The check runs
in a project, and the guard took the one at the folder the event names as the agent's, or
above it. An agent started at the root of a repository, with the paper in `example/`, stands
in a folder that has none: the command was recognised, held to nothing, and went through in
a project that fails. Where no project is at that folder, the guard now reads the words of
the command and holds it to each project that one of them is a path into: `example` after
`cd` or as the argument of `submit`, `example/build/manuscript.docx` after `scp`. A file
that is not written yet names the project its folder is in. Each project is checked once.

The refusal names the project, says that the command named it, and names the check with the
project's folder after it, `manuscript-guard check --stage submission "example"`, because
from where the agent stands the check alone finds no project. The folder comes last on
purpose. The markers want a verb before the word `submission`, and `copy` is one: a folder
called `paper-copy`, written after the word, does not make the command submission-shaped,
where `cd paper-copy && manuscript-guard check --stage submission` is, and would be refused
with the advice it had just followed.

A word is read as it stands and, where the way it is written hides a path, as that path
too. curl writes a file to upload after an `@`, `file=@example/build/manuscript.docx`, so a
word is read from after its last `@` as well. In quotes `=` is not a separator, so a quoted
word is also read from after its last `=`. Outside quotes a backslash and a space are a
space in a name, `my\ paper`, as a shell reads them, and that is the only reading. To
PowerShell a backslash ends a folder's name, so `.\example\ D:\sent` is two paths, and it
is not found. Reading the pieces as well found it, and twice took a piece of a file's name
for the project beside it: `paper` in `cp paper\ draft.docx /backup`, which refused a copy
of an unrelated document and a submission from `paper v2`, which passed; then, once
narrowed to Windows and to a run holding another backslash, in `cp Edited\ paper\
\(JD\).docx /backup`, where the other backslash is a shell's escape. Both were found by
#137's review, and the reading was dropped (Basile, 2026-10-02): a path not found is a
limit that is written down, and a document refused for a project it has nothing to do with
is what this change was decided against. A word of more than 4096 characters or 100
folders is not a path and is not walked: each step down is a look on disk, `..` exists at
every step, and 5000 of them in one word took 34 s.

This is not reading the command as a shell does. Nothing is expanded and nothing is run, and
the guard does not know that `cd` changes folder: it asks of each word whether it is a path
into a project, and a string in quotes is one word. That keeps out a project the command
does not name (Basile, 2026-10-02). The root of a repository is where every other command is
sent from, and a paper below it that fails must not stop a copy of an unrelated `.docx`.
Following a leading `cd` was the other way, and would have left `manuscript-guard submit
example` and `scp example/build/manuscript.docx host:` uncaught, which need no `cd`. What a
command does not spell out is not found, and a word that happens to be the folder's name is
taken for it; both are under Known gaps. A submission-shaped command that names no project
costs about 10 ms more than it did, one look on disk for each reading of each word, and a
command that is not submission-shaped costs nothing more. A script of 2000 different words
written into a file through the shell, if it is submission-shaped, costs about a second.

**A refusal names a command the guard lets through.** The refusal shows the first eight
failures and says what to run for the rest. It used to say `manuscript-guard check
--submission`, and `--submission` is one of the guard's markers wherever it stands in a
command. An agent that did as it was told was refused again with the same eight lines, and
could not reach the list. The refusal now says to run `manuscript-guard check --stage
submission` on its own. Run so, the guard does not match it, and it gives the same verdict,
the stage being resolved before any gate runs. "On its own" is part of the advice: the
command ends in the word `submission`, so after `cp` or `git push` on the same line it is
matched again (Known gaps). `tests/test_hooks.py` sends each command a refusal names back
through the guard in the project that was refused, over a table that a refusal added later
is added to. For the failing check it also runs the command, to see that every failure is
listed and that as many are counted as the guard counted.

**An option is read only where it is written in full.** The guard's marker for the
submission standard is the word `--submission`, and it can only list the spellings the
command line reads. argparse reads any prefix that names one option, which made `--subm` a
spelling the guard did not have. The parser refuses abbreviations, on every command, so the
word is the only spelling of that option (see "Closed since"). It is not the only way to ask
for the submission standard: `--stage submission` is the other, which a refusal itself names
for `check`, and on `build` the guard does not hold it (Known gaps).

**A hook never breaks the session.** Every handler swallows unexpected errors and exits 0.
A guard that crashes on a half-configured project gets removed by the author, and the guards
that were working go with it.

One error is expected, and is passed on. Where a file of the project's own cannot be used
(it does not parse, is not UTF-8, or leaves `check` with no folders or no stage to go by),
`check` stops before any gate, says which file in a sentence written for the author, and
exits 2. A project that could not be checked has not passed, so the submission guard refuses
with that sentence, and the session start says it where the status line would have been. The
gates raise the same error where there is no `paper.yaml` above the folder at all, and there
a hook has nothing to say: a guard that refused on it would refuse every command that names
a `.docx` anywhere on the machine. So both look for the project first
(`hooks._project_root`), stay silent where there is none, and pass on only an error raised
once one was found. Anything else the gates raise is still a fault of the tool, and still
ends in silence.

**A hook reads its event as UTF-8.** The agent tool writes the event on the hook's standard
input as UTF-8, and a name outside ASCII goes as its own bytes, with no `\u` escape. Python on
Windows opens standard input in the ANSI code page, so a handler that read it as text was
handed `manuscript/méthodes.md` as `mÃ©thodes.md`, a file that does not exist.
`hooks._event_text` reads the bytes and decodes them itself. Bytes that are not UTF-8 are read
in the encoding standard input was opened with, as they were before, and a byte that encoding
cannot read is replaced, so that the event is kept: an event read as nothing guards nothing,
and a letter lost from a file's own name leaves the folder and the extension by which the
write guard knows a generated file. The answer needed no change. `json.dumps` escapes every
character outside ASCII, so what the hook prints reads the same in the code page it is written
in and in the UTF-8 the tool reads it as, and a test holds it to ASCII.

**A hook blocks only what is unambiguous.** Writing a machine-written results file is always
wrong. Prose that trips the AI-writing lint is not, so nothing in G6 is enforced this way.

**The same hooks read Codex's input.** Codex runs hooks under the event names Claude Code
uses, takes the same output, and matches a file edit under the names `Edit` and `Write`, so
`plugin/hooks/hooks.json` is one file for both. Two of the four hooks, the session start and
the submission guard, receive what they receive from Claude Code. The difference is a file
edit, which the other two read. Codex makes it with one tool,
`apply_patch`, and hands the hook the text of the patch in `tool_input.command`, with no
`file_path`. The files are named in the patch's headers, relative to `cwd`, and one patch may
write several.

`hooks.patch_paths` reads those headers by the rules of Codex's own parser
(`codex-rs/apply-patch/src/parser.rs` and `streaming_parser.rs`, read 2026-10-02): nothing
before `*** Begin Patch` or after `*** End Patch`; a header is a whole line of the envelope,
which inside an update must start at the first column, since a line of the file's text starts
with a space, `+` or `-`; `*** Move to:` once, and only before the first change to the file
it moves, which an `*** End of File` line there is not. A looser reading would refuse an edit
to a manuscript that quotes a patch, and a stricter one would miss a write. The write guard
refuses the whole patch when any file it adds, updates or moves a file to is generated, and
names those files only, each once. Where the project keeps `results/` is asked of it once for
the patch, not once for each file. After the patch, each manuscript file and each analysis
file in it gets its line, a moved one where it now is. A file the patch deletes is
not refused: removing a fragment whose script is gone is the author's decision, and `check`
reports every binding that pointed at it. And the submission guard leaves a patch alone,
because a patch that writes `--submission` into a file is an edit, not a command.

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
  in two. It is read once: Word writes every text box twice, as DrawingML and again as VML
  in an `mc:AlternateContent` fallback (verified 2026-09-24, Word 16), and reading both
  reported each number in it twice. The fallback is skipped, as the import's reader skips
  it. What Word puts only in a fallback is read from the choice instead: an emoji inserted
  in Word can be a `w16se:symEx` there (pandoc issue 11113; set as text through Word's COM
  interface, one was saved as plain text), and without it "12", the emoji and "34" read as
  1234. The paragraphs of a text box deleted or moved away start no lines: left empty, one
  styled as a heading used to end the reference list it sat in. Nor does a table row
  deleted or moved away, although neither kind of row is wrapped in a deletion. A deleted
  row is marked in its own properties (`w:trPr/w:del`), and a row moved away is not marked
  as a row at all: Word 16 moves the mark of every paragraph in it, a nested table's
  included, and writes no row-level change, since the format has none for a move. A text
  box's paragraphs are left unmarked, the box going with the moved text it is anchored in,
  so they are not counted (verified 2026-09-25: each tracked copy Word wrote reads the same
  as Word's accepted copy). The row's text was dropped but its row and cells still broke
  lines, and a cell styled as a heading ended the reference list there. An inserted row
  (`w:trPr/w:ins`) is read. A table whose every row is gone parts nothing: a paragraph whose
  mark was deleted before it runs on into the one after it, as Word 16 shows it.
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
  detection now runs over text with fences and comments blanked. (Later: it still took any
  `#` line for a heading, and pandoc does not let a heading interrupt a paragraph. `## Methods`
  directly under a line of Results prose is printed as part of that prose, and the
  `p < 0.001` below it passed as the alpha chosen in advance. A setext title was the same,
  `numbered-heading` filed "## 3.84 times higher" in such a line as heading numbering, and
  `\s+` let a lone `#`, an empty heading, take the next line for its title. A blank line is
  not the rule either: a heading directly under a table, a fence, a div or another heading
  needs none. `text/blocks.py` now walks the document a line at a time, knowing what the
  line above left open, and `test_pandoc_agreement.py` holds it to pandoc construct by
  construct. The round trip no longer tags a setext heading. The audit no longer starts a
  reference list at a heading line pandoc prints as prose, and still ends one at any line
  shaped like a heading. The walk reads a construct it does not model as a paragraph, which
  swallowed a real `# Results` under a table of dashes and ran the Methods on over it, so
  for G2 a line shaped like a heading ends the section it stands in whether or not the walk
  places it. One the walk does not place can say Results and never Methods, and a number is
  in the Methods only if the printed headings alone say so too, so such a line can take
  Methods away and never grant them. A title is read as Results through the marks it may
  keep: pandoc prints `# Results` over a rule as a heading reading "# Results", and taken
  literally it matched no Results pattern and re-admitted the Methods rules under it.)
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

**A footnote is read where it stands and where it is referenced.** Pandoc prints a footnote
at its reference, and G2 read its text under the section its definition line sits in only,
so a finding referenced from Results and defined under Methods, `p < 0.001`, passed as the
alpha chosen in advance, while the document printed it as a footnote to a Results sentence
(found reviewing #65). `sections.footnote_index` finds each definition's text and its
references, and a number in it must pass under the section where it stands and under the
section of every reference in the same file (`chains_at`, `Classifier.classify_under`; see
Known gaps for another file): a note referenced
from Results fails there, and one referenced from Methods and from Results must pass in
both. `explain`, `bind` and the annotated copy read it the same way. A number is judged in
no fewer places than before, so nothing that failed passes. The first version judged it at
the references alone, and review of #77 found five ways the gates took text for a note's
that pandoc prints where it stands: a `[^n]:` line pandoc reads as the paragraph above's,
paragraphs a list item or a comment holds, a line of no-break spaces taken for blank, a
note nested in another's, and a note referenced from another file. Each let a Results
claim pass at a Methods reference. Judged where it stands as well, each fails as it did.
The note's text is the definition's line, the lines under it up to a blank one or one that
may start a block, then each block after blank lines indented four spaces or a tab; where
that misreads pandoc, it only adds a section to pass in. Each note's reference chains are
found once, one in Methods and one elsewhere at most, since a verdict reads nothing else
of a section: judged under every section referencing it, a note of a thousand numbers
referenced from a thousand sections took two minutes (the fix-only review of #77).

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

**A mark never changes how the text reads.** The number finder reads raw text, and takes
markup in with a number: `HbA~1c` out of `HbA~1c~`, `CO~2` out of `CO~2~`, `span>7</span`
out of `<span>7</span>`. A mark around what it found left the closing `~` outside, so
pandoc read no subscript, and a number in a code span, `` `x2` ``, got its mark written
inside the span, where the link printed as text. So the annotator places each mark first:
- **Code, equations, a link's text and the front matter take no mark.** Code spans are
  paired a run of backticks with the next run of the same length in its paragraph, which
  is pandoc's rule but for two edges (see Known gaps). Equations are pandoc's dollars,
  looked for outside code: a `$` in `` `df$age` `` opened one that ran to the next code
  span's (review of #76). A dollar sign before a number is a currency's, not markup, and
  `US$5` is marked whole; one after a number stays outside the mark, where `5$ … 10$`
  faced each other across the marks between, and a backslash before a number goes
  inside it, where it escaped the mark's own bracket (the fix-only review of #76). An
  escaped dollar is text: `\$10-\$50` is marked whole, and `5\$` leaves its `\$` outside.
  So is a backslash before anything but a space, a bracket or a backslash, in a number
  read across several runs: pandoc makes text of a symbol after one, and keeps it before
  a letter or a digit, as text or a TeX command, the same inside a mark as outside, so
  `5\%-10\%`, `\~5-\~7`, `5\°-10\°`, `1.2\pm0.3` and `data\2021\05` are marked whole (the
  rounds after the extra one, and the follow-ups). A link's text, the target a URL or an
  anchor, can't hold a mark, which is itself a link. A bracket is a link's text when a
  target follows it; when a second bracket follows, by that one's label, or, the second
  empty or holding a citation or a footnote's marker, by its own text, which pandoc falls
  back to; and alone, by its own text. A label is a link's definition, where pandoc reads
  one, or a heading's title: pandoc reads `[95% CI 1.2-3.4][@smith2021]`, `[…][^2]` and
  `[12][13]` as text, and their numbers are marked (the extra round of #76, and the
  follow-ups). A number in a link's definition takes no mark, and a binding in a link's
  text is put in as its value, unmarked.
- **Inside other markup, the mark goes around the digits.** The mark goes around the one
  run free of markup that holds a digit, inside the subscript or the span, where pandoc
  reads a mark as well as anywhere: around `1c`, inside `HbA~1c~`. When several runs hold
  digits, `10^-3^`, it goes around the whole of what was found, if every sub- and
  superscript in it opens and closes there; brackets in it are escaped in the mark and
  read as text, `12][13`, and a `@` makes a citation, so none goes there. No mark opens
  straight after a `]`, where pandoc read two brackets as a reference, nor after a TeX
  command, which took it for its argument. An ordered list's own numbers take none: marked, the list was a paragraph.
  Otherwise the number is left unmarked.

That rule is a model of pandoc's inline reader, and models of pandoc's readers have been
found wrong round after round in this repository. So the build then asks pandoc: each file
is read with its marks and without, the marks unwrapped and each block compared, and every
mark in a block that reads differently is taken out. Which mark did it is not worked out,
so a paragraph can lose all its marks for one; a number in an HTML tag's attribute,
`width="300"`, is the example the tests hold. What still reads differently after that loses
every mark in the file, so the annotated copy never reads otherwise than the manuscript,
marks aside. Two things are left out of the comparison. A pipe table's column widths: a
longer row, marks in it, makes pandoc give the table widths, which changes the layout of
the annotated copy's tables and not their words. And a citation as written, which pandoc
keeps and citeproc replaces: with a mark on its locator, `p. 33`, it differed, and the
paragraph lost every mark (review of #76). A number left unmarked is
still listed in the appendix, with the reason, and the build says how many there are. It
costs two runs of pandoc's reader a file, and a third where a mark is taken out.

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
substitution — `[]{#mg-p-main-12}`, which pandoc emits as a Word bookmark: invisible, and
surviving an edit. This paragraph used to add "travelling with the paragraph when somebody
cuts and pastes it". Word does not carry it; "A move, the way Word makes one" below says
what it does instead and how the move is read anyway. When the document comes back, the
identifiers say exactly which paragraph is which, so a move is a reordering of text already
on disk rather than anything imported. That makes it safe for
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

An identifier is positional, though: the file and the block's place in it once the front
matter is stripped. So it means something only under the rules that assigned it, and those
rules change. The front-matter reading changed in plugin release 0.2.13. After that, a
document built before the change and imported after it had every identifier a block out of
step: `import --apply` wrote three paragraphs' text over three others and printed "merged 3
reworded paragraph(s), bindings intact". A review round's anchors went the same way, and G13
compared the wrong paragraph and passed. The same happened, with no change of rules, to a
document forced in after a paragraph was added to the source above the one a co-author
edited: `--force` said to check every hunk, and the plan showed what each edit became,
never which paragraph it replaced.

So the document now records what each identifier named: for each of its paragraphs, in its
order, a short hash of the source text and one of the block before it, beside the source
digest (`roundtrip.PARAGRAPHS_PROPERTY`, split across properties short of the 255
characters Word may cut one to). The block before is there because text alone cannot tell
two paragraphs apart that read the same, and a paper repeats "Not applicable." under one
declaration after another: with one more added above them since the build, the first one's
identifier named the new one, read the same, and a co-author's ethics approval went under
"Consent to participate". A paragraph whose text is found once in its file, then and now,
needs only its text to match; one that repeats needs the block before it to match too.

The record also hashes the blocks without an identifier around each paragraph, up to the
paragraphs on either side (`roundtrip._beside_of`, `Numbering.beside_changed`). That covers
headings, captions, tables, comments and link definitions, and a heading written straight
above the paragraph with no blank line, which shares its block and sits outside the text
hash. It reaches across files, in the order the build prints them (`printed_order`), since
the main text's files are one document: the heading opening the next file stands directly
under the last paragraph of this one in Word.

A heading run into a paragraph in Word is recognised by the heading beside the paragraph
having vanished while its text turned up in it, and the heading looked at is the one in the
source now. When one of those blocks changed since the build, that is not the heading the
co-author ran in: one renamed or removed, one past a comment Word does not show, a table's
caption, which pandoc prints above the table. The run-in then merged, "MethodsPapa..." under
a heading the file no longer has. So a rewording is not merged into a paragraph with a block
without an identifier around it changed since the build. A paragraph reworded beside it
counts for nothing, as no heading can have stood where a paragraph stands. Nor, in a
document built from other inputs than are on disk, is a rewording merged into a paragraph
beside a heading or caption missing from the returned document. Its source can be unchanged
and its text not, with a value or a citation in it: "Results in 4000 reports", run in, was
typed into prose where a binding now prints 4100.

`import` compares, moves and merges only the paragraphs whose identifier passes that test,
or that are followed (below), and names the rest as not compared, whether they came back or
not; `respond --open` keeps a comment's anchor only on such a paragraph. It does not matter
why an identifier came to name other text, a source edited since, a release that numbers or
tags paragraphs by other rules: each is caught the same way, one paragraph at a time. What
is left out still counts for what
is compared beside it. A paragraph joined in Word to one left out is refused as a join, as
is one whose next paragraph as sent is left out and did not come back, which a join retyped
across the boundary looks like: merged as a rewording, either put the other paragraph's
words in the source twice. A paragraph the document carried with no identifier, which has
one now - a list item made a paragraph since the build, or a block a later release tags - is
not in its record and so never compared; it is weighed as a join into the paragraph before
it, by its text, as main weighs every paragraph. Left out, the co-author's join of it into
that paragraph merged as a rewording, exited 0, and put its text in the source twice. A
document that records nothing has no order as sent, and the one paragraph it can leave out
without trusting the rest less, a value it may never have carried, is weighed the same way.
A number for the rules was tried first and had to be bumped by every change to them; three
reviews each found a change that would not have.

**A paragraph whose identifier shifted is followed where nothing beside it changed.** One
paragraph added to the source since the build, or removed, moves every identifier below it
by a block, and refused, every co-author edit below it had to be carried over by hand. So an
identifier that no longer names its paragraph is followed to the one that does
(`roundtrip._followed`) when what stood around the paragraph at the build stands around it
now: its whole record - its text, the block before it, the blocks without an identifier on
either side up to the next paragraphs - and the text of those two paragraphs, before and
after it as the build prints the document, across files. The record holds nothing of the
paragraphs beside, and `import` weighs a join against the paragraph after: with one added
there since the build, the join was weighed against text the co-author never had. That
window has to be found once in its file then and now, and the paragraphs compared have to
keep their order, or a move the author made reads as the co-author moving the paragraph
back. The paragraph directly beside what changed is not followed, and nothing is in a
document built before the record held the blocks beside each paragraph.

#84 tried this first on the record as it was, which hashed the text from the marker on and
the block before, and looked past each kind of block a co-author never had to find the
heading run into a paragraph or the paragraph joined to it: past an added paragraph, then a
list, a quotation or a sub-heading, then a table or an equation. Each of three rounds of
review found the next kind. The fourth found two that no such looking could reach: a heading
written straight above the paragraph with no blank line, outside every hash, renamed or
removed since; and a heading holding a value re-run since the build, whose source had not
changed while what it printed had. The window above answers the first. For the second, a
followed paragraph is treated as one in a document built from other inputs, whatever the
stamp says, since its record vouches for the source around it and not for what that
printed: its rewording is refused beside a heading or caption missing from the returned
document, and when its next paragraph as sent did not come back. "None." joined in Word with
a value paragraph printing 4000 then and 4100 now read as a rewording, not a join, and
"None. 4000" merged, a number typed beside the binding that prints it. A rewording of the
paragraph before a followed one that did not come back is refused too: main left the
followed one out of the comparison, and refused that rewording for it.

A followed paragraph is read under the identifier it has now: the returned document is
renamed, not the source. The identifier it has now can be carried in the returned document
by another paragraph, one not followed, since the paragraphs moved: that one is read under a
name no paragraph has (`roundtrip.named_now`). Read under its own, with the followed
paragraph deleted in Word, its rewording merged into the followed one. `respond --open`
anchors a comment on a followed paragraph at the identifier it has now, which is what G13
looks up.

The paragraph directly below what changed is never followed, and so not compared, and the
first review of #114 found what that did beside the paragraphs that are. Cut and pasted into
a followed paragraph in Word, it was not looked for, since the paste checks weighed only the
paragraphs compared: its words went into the source twice, or, as a value, were typed as a
number beside the binding that prints it. A followed paragraph moved in Word above it was
written below it. And a value re-run since the build, pasted into a followed paragraph, was
weighed as it prints now. Main did each of these beside a paragraph the author had reworded,
and the fixes are main's (#116, #119):
- a paragraph the document was sent with that did not come back with text of its own is
  looked for, one not compared by a paragraph whose source reads now as its did then;
- a paragraph's bindings and citations are not taken to print as they did, and a followed
  paragraph's are treated so too;
- a move past a paragraph not compared is withheld.

The fix-only review found the first rule still missed what Word 16 does. A cut paragraph's
identifier stays in front of the next paragraph's own, or on the emptied line, and the
paragraph counted as having come back. #119 counts it as gone wherever the text its
identifier holds, from its bookmark to the next one's, is not its own
(`merge._came_back_whole`). That also covers a followed value whose identifier slid onto a
paragraph not compared, which had read as a join. Where each bookmark sits is read under
the names the returned document is read under (`roundtrip.named_now`): under the old ones,
a block holding a followed identifier or a renamed one could not say whose text either
held, and a paragraph standing there untouched counted as gone.

A document from before paragraphs were recorded is refused only where it matters, which
can only be judged against the text it was built from. If anything it was built from has
changed since, it is refused, whatever is passed. If not, it is refused when a file it
carries numbers differently under the front-matter rule of releases up to 0.2.12, or of
those from 0.2.13 until 0.2.47, which stripped a header pandoc prints. A release that only
tags fewer blocks needs nothing more: 0.2.45 stopped tagging lists and quotations, kept
every other block's number, and the identifiers an older document carries on them are named
as not compared. One that tags more does: 0.2.49 gave a paragraph that is only a value an
identifier, which an older document may or may not carry. Such a paragraph is compared if
the document carries it, and named if not.

A review round needs nothing of the kind, because G13 no longer compares by identifier. The
round keeps a hash of the text of every paragraph as submitted, and the paragraph a reviewer
commented on counts as unrevised while the manuscript still holds that exact text: in any
block, or in any run of a block's lines between the headings and markers inside it, with
whole-line HTML comments left out. Compared by identifier, it broke without any change of
rules as well: a paragraph added above the anchor during the revision pointed it at a
neighbour, and a paragraph nobody touched passed as revised.

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

A slot's text is not all that decides whether its paragraph can be found again: `tag` reads
what surrounds a block too. A footnote is marked, and prints as text, when an indented block
below it would run into it; swapped in Word with the paragraph above it, it landed over a
plain paragraph, became a note again, and the next build printed nothing of it in the body,
while `import` said it had reordered a paragraph. A `-->` typed into a paragraph can close
a `<!--` left open above it, and pandoc then reads both, and all between, as one comment. So
before anything is written, each file is worked out as it would be written and read the way
`tag` reads it, and a paragraph that would not come out marked - at the place the splice
put it, with the text written - is withdrawn, one kind of cause at a time: its rewording is
refused, or the moves in its section are held (see "Closed since").


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
comment, exit 0. Display maths was also read from the document as sent, an equation directly
after a paragraph being taken for part of it, however its source was written. That rule went
once no paragraph with `$$` anywhere in it carried an identifier: it then found only an
equation standing on its own, or a list item or quotation holding only maths, which Word
also shows as an equation, and it held the paragraph above for nothing, refusing its
rewording and a swap with the paragraph before it. And a held paragraph whose only change is
a no-break space pandoc put in and Word's editor took out again has nothing to merge, as an
ordinary one has not; it was refused instead. That is decided only for a source with no
no-break space of its own and no binding or citation: asked of every paragraph, the check
dropped a co-author's change to one the author had written, with "nothing came back". An
author can write one as `\ `, as the character, or as an entity pandoc reads,
`&NonBreakingSpace;` and `&#0160;` included. It is also decided only when no new text stands
beside the paragraph. Only the part carrying the identifier is compared, so when the part
after an equation had been reworded, skipping the paragraph dropped that rewording.

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
named nothing. When the paragraphs without an identifier all came back, only reordered, one
of them out of place is named with them, as having come back in a different order. Named in
both reports, a swap of two list items was said twice, each report naming its own share of
the items, and a list item was called a heading. The closing note on what import could not
look at counts a figure or equation that went missing or moved as a change outside a table:
it had said that nothing outside a table changed, beside the report that a figure could not
be found. A display equation is a block of the same kind, known by its text. Word
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

The writer and the tagger have to read an opening the same way. The tagger judges a block by
pandoc's rules, and the writer kept a short list of its own: `B) the ratio was...`, `IV.
The`, `| The` and `Table: The` merged as typed, pandoc made a list, a line block or a caption
of them at the next build, `tag` gave the paragraph no identifier, and its next edit in Word
was dropped with nothing reported. The writer now asks the tagger's own reading of a
numbered list and a caption, so "E. coli" stays a sentence and "IV. The" is escaped, and the
property is tested as it is meant: whatever the merge writes from Word, pandoc reads as one
paragraph and `tag` names it, read alone, under a paragraph and under a table - or the merge
is refused, and says why. That is a property of what the writer writes, not of every merge: a
stretch kept from the source can take a shape of its own once the stretch before it is
reworded, as a lone `:` on a paragraph's third line does when the first two are joined. That
is caught by #69's check, which works the file out as `apply_plan` would write it and reads
it as `tag` does. The tagger, for its
part, took any HTML tag it did not know for a block and counted an escaped brace. Pandoc
reads a tag it does not know as inline and `\{` as a brace, so "Concentrations <LLOQ and
>ULOQ were excluded." lost its identifier when the tagger learned pandoc's blocks. Its block
tags are pandoc's own lists now, HTML's and the DocBook and EPUB ones pandoc also reads in
markdown, checked by a test that asks pandoc about each tag where it stands. A first version
held HTML's list alone, measured rather than read from pandoc's source, and marked a table
row under a line holding `<example>`. And `import` escapes a `}` as well as a `{`, so the
braces a co-author types never look like half of a TeX group. Only unescaped braces count,
so a pair split across a binding - one brace kept from the source bare, its partner edited
in Word and written escaped - no longer pairs, and that rewording is refused rather than
merged into a paragraph the next build could not name. `main` before #72 wrote a `}` from
Word bare and merged many of these; the round-3 review of #72 counted 212 in a differential
of 4,174 brace-heavy rewordings. #90 tried writing Word's half bare again where the source's
own stretch had a bare brace, and each of three review rounds found a shape where the bare
brace completed what pandoc reads as attributes, the paragraph printing wrong while `check`
passed: `{{results.x}}{.y}` printed a value shown as `[pooled]` as "pooled", `]{.c}`
closing a `[` kept from the source dropped the brackets and braces, and a `}` closing a
kept `{` straight after a `]` or a link, `[a [b] c]{k={{results.x}}}`, dropped the value.
`_reads_as` reads spans, links and values too simply to see any of these, so the half from
Word stays escaped and the rewording is refused (see Known gaps).

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

No text box is read, and no AlternateContent fallback, which repeats its choice. So a
character Word writes only in a fallback is read from the choice: an emoji inserted in Word
can be a `w16se:symEx` in the choice, with the character as text only in the fallback. The
document attached to pandoc issue 11113, saved by Word 16, holds six emoji written that
way. Read as nothing, an emoji the author inserted never came back ("nothing came back: the
document matches the manuscript on disk"), and one already in the source read as deleted:
`--apply` took it out and reported a reworded paragraph. Word 16 did not write that form for
an emoji set as text or typed through its COM interface, nor on saving a built document
holding one, untouched or edited beside it (verified 2026-09-25), so which way of inserting
one produces it is not known here.

A character is read as the font it is in draws it (`wordfonts`). Insert > Symbol with the
Symbol font writes no text but `<w:sym w:font="Symbol" w:char="F0B1"/>`, for every character
of the font, and text typed in the Symbol font is in that font's encoding: an `m`, or the
private-use U+F06D, drawn as μ. Read as nothing, an inserted ± was dropped and the rest of
the edit merged without it ("no funding ± none." became "no funding none."), a μ in "5 μg"
merged as "5 g", and a minus put before a bound number came back as "nothing came back";
read as written, a μ typed in the font read as "5 mg". The Symbol font is read through
Adobe's encoding as the Unicode Consortium publishes it, less 0xA0, € in Adobe's later
Symbol font: the Symbol font Windows ships has no glyph there. Which font draws a character is
decided as Word decides it, and each rule was checked against Word 16, whose own text
reports a character the Symbol font draws as U+F0xx (verified 2026-09-25): `ascii` draws
ASCII and `hAnsi` the rest of Latin; `w:hint="eastAsia"` sends ±, °, × and twenty other
Latin-1 characters, and the symbol range U+F000-U+F0FF, to the East Asian font; a font comes
from the run, else its character style, else its paragraph style, else the defaults, or from
the theme where a `...Theme` attribute names one. `w16se:symEx` names its own font and is
read in it the same way.

What has no text is not given one: a Wingdings character (in 1,813 Word files on the
author's machine, all 382 `w:sym` were Wingdings or Wingdings 2 check boxes and arrows, and
Word's AutoCorrect turns `:)` and `-->` into such a symbol, its entries being formatted
ones), a piece of a tall bracket, or a Symbol code with no glyph. Typed in another symbol
font it is the same: `J` and `ü` typed in Wingdings or Webdings are saved as that text, and
Word reports them as U+F04A and U+F0FC, its smiley and check mark (Word 16); read as written,
"no funding J." went into the source. Word marks a symbol font in the document's font table
with `w:charset w:val="02"`: Symbol, Wingdings and Webdings, not Segoe MDL2 Assets, whose `J`
is a J.

A paragraph that came back holding a character with no text is refused and the character
named ("Wingdings character F04A"), even with nothing else edited: merged, the rest of the
edit landed without it. So is Symbol-font text whose font comes from a style, the
defaults or the theme, with its own reason: it is read, but a style's font is not taken
as exact. A private-use character that
another font draws - a symbol font's code, or an icon font's such as Segoe MDL2 Assets - is
kept as the character it is, and named without the font, with a reason of its own: the source
would keep it, but the build draws it in the body font. The source can hold one pasted from
an old document, and dropped from the text, or named after a body font the co-author
changed, it put its paragraph beyond merging. What the document as sent held already is not
the co-author's and is not refused; each is counted, not each kind, since a second of a code
the paragraph held already was merged. The author chose refusing over reading these as
nothing or as a space, on 2026-09-25. A paragraph without an identifier, only listed when it
changed, is compared the same way and listed with each such thing named, "Funding
[Wingdings character F04A]": by its text alone, a heading that gained a smiley typed in
Wingdings read as unchanged, and import said the document matched the manuscript. A heading
holding one that came back in another place is named the same way, or the report named it
twice, once as out of place and once in the new order.

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

## A move, the way Word makes one

A review of the Word round trip reported that a paragraph cut and pasted with Track Changes
on came back as "deleted in Word, left in place here", with its pasted copy refused as a
split, and that the advice printed with both - delete it in the .md yourself, make the
addition in the .md - led an author to delete a paragraph full of bindings and retype it from
Word's copy, which has numbers where the source has bindings. Nothing was written to the
source; the advice did the damage.

Driving Word 365 over COM on the example's own build showed it was wider than that. Every
move test so far had moved the whole `<w:p>`, bookmark and all, which Word never does: the
identifier is an empty bookmark, and Word does not carry an empty bookmark with the text it
cuts. With Track Changes on it stays in the moved-from copy; without, it moves onto the next
paragraph. Text pasted or typed at the start of a paragraph goes in behind that paragraph's
bookmark, so the paragraph a move landed in front of lost its identifier to the moved one.
So no paragraph cut and pasted in Word had ever been moved: every one was refused, and two
paragraphs moved together, or one moved to the top of its section, were reported as a join.
Pressing Enter at the start of a paragraph reported that paragraph deleted. And pandoc's
reference document sets `w:doNotTrackMoves`, so with Track Changes on Word wrote a move as a
deletion and an unrelated insertion, and left out the one piece of markup that pairs the two
places.

What Word records is now read. The build removes `w:doNotTrackMoves`, and Word then names
each move, with the same name on the range it left and the range it arrived in. Where a move
took whole paragraphs, as many arriving as leaving, each identifier goes from the paragraph
it left to the paragraph it became; the move is applied from the text on disk, and a
rewording made after the move is merged like any other. A paragraph whose mark and text all
arrived, and which deleted nothing it was sent with, was not in the document as sent, so an
identifier at its start goes back to the paragraph after it: past a paragraph that arrived
and was deleted again, not past one deleted whole, and onto an empty line only for a
recorded move (text typed on the empty line a spacer such as `&nbsp;` renders as stays
refused as such).

What Word does not record is not guessed at. The first version of this change also recovered
moves made with Track Changes off, by matching whole paragraphs word for word. Three rounds
of independent review each found wrong writes in it, where `main` had refused: a paste
carrying a deleted paragraph's identifier merged as that paragraph, the moved text in the
source twice under "bindings intact"; a paragraph split with a moved one pasted between the
halves merged as its first sentence; a heading pasted with a paragraph replaced the one it
landed on. Each fix opened the next hole, because every identifier the text rules placed was
one fewer piece of new text for the split check to see. After the third round the recovery
by text was taken out. A move Word did not record is refused and named as a move - "moved in
Word, left in place here", with Word's copy shown and the advice to move it in the .md and
never retype it - and the skill asks co-authors to keep Track Changes on. Two exact rules
stayed: an identifier left on an empty line goes back to the next paragraph when that has
text and reads exactly as the identified one was sent (Enter without Track Changes; a line
holding only a symbol read as the empty line a `&nbsp;` spacer renders as, and took the
spacer's identifier), and an identifier on a heading, a caption or a reference entry is
taken off it (the last paragraph of a section, deleted without Track Changes, used to merge
the heading's text into itself, on `main` too).
Recognised by its text at first, a heading retitled in the same round was still merged -
"Study design", as Word's own saved file showed - so a paragraph's role is now read from its
style: a heading by its outline level, a caption or a reference entry by its style's name,
never by the id, which Word renames when it saves in another language (a Japanese Word saves
pandoc's `Heading1` as `1`). Three kinds of block keep their identifier all the same, since
reported deleted they would invite deleting a paragraph that is there: a paragraph restyled
as a heading in Word, its words mostly its own; a paragraph the heading before it was
joined into, which keeps the heading's style and is refused as a join - known by that
heading gone from the document and its text turned up in the block, as a join is known
anywhere, since the paragraph may have been reworded in the same round; and a paragraph
sent with the role it has, such as a note the source styles as a caption.

The checks that came out of the review rounds guard the tracked path as well:

- A paragraph that arrived with Track Changes on vouches for nothing beside it. The split
  check looks for new text beside a changed paragraph, and a moved paragraph pasted between
  the halves of a split, carrying its identifier, stood where the second half had. It
  vouches for nothing whatever it still holds: with its moved text deleted, or replaced by a
  symbol with no text, it was looked past as an empty line is, and the split merged as its
  first half. Only an arrived line that holds nothing, and carries no identifier or only
  those of paragraphs sent with no text - a `&nbsp;` or `<br>` spacer, or a line holding only
  maths or a picture - is looked past, as the empty line it is, and what lies beyond it
  decides. Enter pressed on a spacer reads as arrived, and treated as a paragraph that
  vouches for nothing it had the rewording beside it refused. A spacer and the paragraph
  under it cut together and pasted between the halves of a split are one move to Word, and
  treated as a neighbour, the spacer vouched for the split; looked past, the moved paragraph
  beyond it does not.
- Text on a line sent empty is new text. Delete pressed at the end of a split's second half
  takes in the spacer line under it, and the second half then carries the spacer's
  identifier: as a paragraph with an identifier, it vouched for the split, and the paragraph
  was merged as its first half, on `main` too. The cost: a rewording beside a spacer line
  that anything was typed on, or that an untracked deletion left its identifier on, is
  refused as a split with it, where `main` refused only the spacer line. With the neighbour
  shortened, that cannot be told from the join.
- A paragraph is refused when new body text without an identifier is made mostly of words
  it lost: four of them at least, in order. A split with a paragraph cut in between
  without Track Changes shows nothing else: Word keeps the identifier of every paragraph but
  the first of a cut, so the pasted paragraph stood beside the first half as if nothing had
  moved, and the first line of the cut, a spacer or an equation, landed without one. A
  sentence cut out and pasted as a paragraph of its own is the same loss. A heading, a
  caption or a reference entry is not weighed: Word gives a split's second half the body
  style, and a heading added in the same round, sharing "of hepatic injury" with a
  rewording that dropped it, had that rewording refused. Three words are never enough:
  "of" and "the" are often two of them. Words are compared as written, so a four-word
  second half that gained a capital, as a sentence of its own, is one word short: compared
  in any case, a body line "Reports of hepatic injury" refused the same rewording.
- A move is not applied in a section that gained text the document as sent did not have
  (a split's second half, a new paragraph, an edited heading or caption, which the report
  quotes), or that holds an identifier on text that is not its own: where its paragraphs now
  stand cannot be read with certainty. A paragraph moved in from another section standing
  beside the new text does not hide which section that is.
- A rewording that holds the whole of another paragraph is refused, and so is one that
  gained most of the words of a paragraph gone from its place, and an identifier on text
  that reads exactly as another paragraph, a heading or a caption did.
- The paragraph gone from its place is weighed as it printed at the build, not as the fresh
  build prints it, and every paragraph the document was sent with counts, compared or not,
  that did not come back with text of its own. Word 16 does not delete a cut paragraph's
  identifier with its text: it goes in front of the next paragraph's own, or stays on the
  line the cut emptied. Taken for the paragraph having come back, a paragraph cut and pasted
  onto the end of another was never looked for there, and the one it went into merged
  holding it, when the `.md` had reworded it since, or beside a paragraph it had reworded,
  which the identifier's block then read as a join with. So each identifier is read with
  the text it holds, from its bookmark to the next one's (`merge._held`, from
  `docxtext.Block.at`): Word keeps a joined paragraph's bookmark where its text began, and
  one left in front of another's holds nothing. A paragraph whose text is known came back
  where its identifier holds that text; one whose text is not known, where its identifier
  holds text that does not read exactly as another paragraph or a heading as the fresh build
  prints them (`merge._came_back_whole`). Read by the block instead, a paragraph deleted,
  joined or moved in front of one the author had reworded left two identifiers on text
  neither could be told to hold, the reworded one, standing there untouched, counted as gone,
  and every rewording that gained five words or a digit was refused. Where a bookmark's
  place is not known, as for one Word's tracked changes carried from another paragraph, only
  a paragraph whose text is known, and in the block, came back there. An identifier on a list
  item or a block quotation is taken off, as one on a heading is (`merge._off_headings`):
  the build gives neither one, and a lead-in sentence cut from before a list left its
  identifier on the first item, which, edited, merged over the lead-in. So is one on any
  other kind of block the build gives no identifier, read from the fresh build and not
  listed: the term of a tight definition list, a div with a style of its own, a code block.
  A block's kind is its style's name and what its numbering draws (`docxtext.Block.style`),
  never an id: Word 16 saved pandoc's `BodyText` as `a0` and its numberings 1000 and 1001
  as 1 and 2. An identifier stays on a block of such a kind only where that is the kind its
  own paragraph was built as. The second paragraph of a list item has an identifier and is
  numbered with no marker; kept on the item after it because some identified paragraph
  was numbered too, the item was written over it.
  Weighed as printed now, a paragraph that is only a value, printing 4000 at the build and
  re-run to 4100 since, cut and pasted onto the end of another, was nowhere in the words that
  one gained, and "...dates. 4000" merged, a number typed beside the binding that prints it;
  joined into "None." above it, "None. 4000" read as no join and merged the same way.
  Weighing only the paragraphs compared, a paragraph the `.md` reworded since the build,
  pasted into another, merged there with its old words, and the source had them twice. So
  in a document built from other inputs only a paragraph's words that touch none of its
  bindings and citations are taken as sent (`merge._as_sent`), and it is weighed as the
  fresh build prints it too, as before; either reading refuses. A word with a value in it
  is not taken: kept apart, the full stop in "4000." and the dash in "2.89–5.12" were words
  of their own, found nowhere among the words that came back, and a paragraph of values read
  as known. One that is not compared is read from a paragraph whose source reads now as its
  did then (`roundtrip.Numbering.same_text`). Where nothing it said is known - values alone,
  or a paragraph the `.md` changed or dropped - a rewording that gained five words in a row,
  or a word with a digit in it, is refused, since those words could be it; and a paragraph
  whose next as sent is such a one and did not come back is refused, as a join cannot be
  weighed. Five is the floor a paragraph pasted whole is looked for from. Refusing any
  rewording that gained a word held back every ordinary edit in the document once Word
  deleted a paragraph the author had also changed. A copy is looked for in the paragraphs as
  they came back too.
- A move is not applied in a section with a paragraph that is not compared standing between
  two of its paragraphs as returned. Such a paragraph has no slot, and stands between
  sections in the source; standing inside one in Word, a move passed it, and filling the
  slots put the moved paragraph on its other side: the author reworded Papa, the co-author
  moved Bravo above it, and Bravo was written below Papa.

A fourth round, on the tracked path alone, found the display-maths move above, the hidden
section, and a paragraph pasted onto the end of another merged with it while the report
advised keeping the vanished original: the text in the source twice. Each is refused now.
A document built before this change still asks Word not to record moves, and `import` says
so when one comes back, rather than naming a version the author has no way to check.

`tests/test_roundtrip.py` builds each case from the markup Word wrote, with a helper whose
documents read the same as Word's own saved files, checked block by block. The pattern is
the one this file keeps finding: the tests simulated what the code assumed an editor does,
not what the editor does.

## The build records what each paragraph printed

`import` compares the returned document with a fresh build of the source. That is what the
co-author had only while the source and its results stand as they did, and the author goes
on working while a draft is out. Three reviews in a row found the same thing under
different names: what a paragraph deleted in Word had said, once the `.md` changed it;
what a value printed before the analysis was re-run; which caption stood under a sentence.
Each was guessed at, by a rule that refused too much (#116's five words or a digit, which
held back five of twenty ordinary sessions) or wrote the wrong thing (a caption over the
sentence above it, #120). The record written in #56 and #93 keeps hashes of the source,
which say whether a paragraph changed and never what it said.

So the build writes down what it printed. After pandoc has made a document, the build reads
it as `import` will read it when it comes back (`docxtext.blocks`) and writes every block,
in order, to `build/records/<name>.json` (`roundtrip.write_printed`):

- a paragraph with its identifier, its text as printed, values and citations as they
  print, and its kind (`Block.style`, `Block.role`);
- a heading, caption, list item, quotation or any other text without an identifier, the
  same way without one;
- a table, a figure or a displayed equation as a marker with no text, and the digest that
  tells it from the others of its kind (`Block.key`), so that the import can say whether
  it is still there;
- the source stamp of the build, so that the record serves no document built from other
  sources, and which of the build's two documents it describes, the paper or the
  supplement, since both carry the same stamp.

The name is the SHA-256 of the file's bytes, and the document carries that name in one
property (`manuscript-guard-printed`) and none of the text. `import` uses a record only if
the file's bytes hash to the name the document carries, its stamp is the document's, it
describes the document being imported, and it has the shape a build writes
(`roundtrip.read_printed`). The name comes from a returned document, which anyone may have
written, so only 64 hexadecimal digits are taken for one; and bytes that hash to that name
say they are the file named, not that a build wrote it. A record written by hand with a
list for an identifier ended the import in a traceback, and the supplement's record passed
for the paper's. So every value must be of the type written, with nothing there that is not
written, and anything else is not this document's record: the import says so and goes on
without it.

**Where it lives, and why not in the document.** The first plan was to put the text beside
the hashes, in the document's properties. Measured on `example/`, whose main text is 751
words in 32 blocks: the text as JSON is 6.5 kB, a hash for each word 4.3 kB, a hash for
each run of five words 5.2 kB. Shingles are no smaller than the text and cannot answer what
is asked: "most of its words, in order" is counted over words, and "reads exactly as" needs
the text. A hash for each word is undone with a dictionary. That left the text, and text
in a document's properties stays there through everything a co-author deletes before
sending the file on. So the record is a file beside the build and the document names it.
It is the paper's own text and nothing else, it is on the disk that already holds the
source and `build/manuscript.md`, and `init` puts `build/` in `.gitignore`, so it is not
committed and not sent. The supplement's record is its own file (2.1 kB on the example).

**What that costs.** The record is on the machine that built the document. Imported
anywhere else, or after `build/` was cleaned, the document is read by the rules it was
read by before, and the import says so in one line that names the file it looked for. A
build never removes a record: a document sent last week must still import exactly after
ten rebuilds. A build that prints the same text names the same record, so the folder grows
by one small file for each build that printed something new, a few kilobytes each. They
are safe to delete; a document whose record is deleted is one built before the record.
`import` builds the source twice to compare with, into a scratch folder, and records
neither. A record already there is left alone only where it holds the bytes it is named
for: one cut short is written again by the next build of the same text. Each writer writes
under a temporary name of its own and renames it into place, so two builds at once do not
meet on one file. A build that cannot write the record still makes the document, warns
(`record-not-written`), and has the document name the record all the same, so that its
import says which file it looked for and did not find.

**What the import reads from it** (`merge.plan_import`, `printed`):

- What every paragraph the document was sent with said, compared or not, re-run since or
  not. A paragraph gone from its place is looked for by those words and no others, so
  #116's five-word rule is not asked, and a paragraph printing a re-run value is no longer
  taken for one that gained a number (`_took_vanished`, `_swallowed`, counted from what the
  paragraph printed and not from the fresh build).
- Whether an identifier came back on its own paragraph (`_came_back_whole`): it holds what
  the paragraph printed, or it does not. A sentence typed where a cut paragraph stood, or
  after its identifier once Backspace had joined the emptied line onto the paragraph
  before, is not that paragraph, and the paste of its old text elsewhere is refused.
- What stood beside each paragraph (`_gone_beside`, `_off_as_sent`), read with where the
  identifier's bookmark sits in its block (`docxtext.Block.at`). Word puts what is typed or
  pasted at a bookmark after it, so the text in front of an identifier is never its
  paragraph's. Each place below was made in Word 16 over COM before it was written down.
  - *Behind other text.* The paragraph's text deleted and Backspace pressed on the emptied
    line, its identifier is at the end of the block above. Holding no text there, the
    paragraph is gone, whatever was done to that block. Holding text ("Funding", three
    Backspaces and "ers" leaves "Fund", the bookmark, "ers"), that text was typed after the
    join, or is the paragraph's with the block above run into it and edited. No reading of
    it is one paragraph reworded, so nothing is written: the join is reported where the
    block above came back whole (`_took_in`), and the paragraph is refused otherwise.
  - *At the start of its block.* The block is the paragraph, or text without an identifier
    that stood beside it and is gone as it was. Under it: deleted, a paragraph leaves its
    identifier on the block after its own, past any table, figure or equation deleted with
    it. Above it: its line joined up and the block above selected whole and typed over, the
    bookmark is in front of what was typed. Where one of these is gone,
    the kind and the words decide, and what they cannot decide is refused and not reported
    deleted: the caption under a deleted sentence that reads like it, a block of the
    paragraph's own kind reworded past most of its words. A block of another kind than the
    paragraph's that does not read like it is weighed against text of that kind gone from
    anywhere in the document too: a heading cut and pasted onto the line the paragraph's
    text was deleted from, and retitled there, is that heading, as main reads it by its
    style.
  - *At the start of its block, with nothing beside the paragraph gone.* The block is the
    paragraph, or a new block typed where its identifier slid: the paragraph deleted whole,
    then a heading typed in front of the next one, which goes after the bookmark and takes
    that heading's style. Nothing the document was sent with is gone, and it is byte for
    byte the paragraph given a heading's style and rewritten. One reading has to give, and
    the one that writes a heading's text over a deleted paragraph gives: the block is read
    as `main` reads it (`_off_headings`). Of a kind the build gives no identifier, and not
    reading like the paragraph, it is not the paragraph, which is reported deleted. So a
    paragraph restyled as a heading, a list item or a quotation and rewritten past most of
    its words is reported deleted with the record as without it. Of the paragraph's own
    kind, or reading like the paragraph, it is the paragraph.

  The first version read only the text under a paragraph, up to the next table, figure or
  equation, and took a block for the paragraph where nothing there was gone. Round 1 of
  #121's review joined an emptied line up to the heading above and retitled it: "Funders"
  was written over "This work received no funding.", which main reports deleted. Round 2
  deleted "Reporting follows the checklist..." and typed "Reporting" as a new heading in
  front of "Results": with nothing gone, "there is nothing else for it to be" made the new
  heading the paragraph, and the source line became `Reporting`.
- A block refused because it cannot be told from its paragraph is no new text beside the
  paragraphs around it: a rewording in the one before it or after it merges, as on main.

A document without the record keeps every rule it had (`_off_headings`, `_as_sent`,
`_took_unknown`). `tests/test_ordinary_sessions.py` holds the sessions the reviews of #116,
#119 and #120 measured against main, 102 of them, so that the next change is measured by
the suite and not by a script in a scratch folder. With the record, six of them merge
something main held back and none holds back anything main merged; without it, all 102
read as on main. (Four more merged at first, each a paragraph given a heading's, a list
item's, a quotation's or a term's properties and rewritten. They are the same bytes as the
new heading of round 2 above, and are held back again, as on main.)

That was true of the 102 and said without that limit. None of their four papers has a block
of a paragraph's own kind, and none joins an emptied line up, so they could see neither the
refusal the record adds nor the heading written over a paragraph. Round 1 of #121's review
added a fifth paper, with a line block, the text after a displayed equation and a div with
no style, each between two paragraphs, and 23 sessions. Of the 125, with the record: six
merge something main held back; four hold back a rewording main merges, each a paragraph
rewritten past most of its words beside a block of its own kind deleted in the same round
(see Known gaps); four write nothing where main writes a block's text over a deleted
paragraph; and 111 read as on main. Under the first version of this change, ten of the 23
failed.

## A fence is a line pandoc reads as one

The fence reader split lines with Python's `splitlines`, which also breaks at a vertical
tab, a form feed, U+001C to U+001E, U+0085, U+2028 and U+2029, and it took a closing
fence's surroundings off with `str.strip`, which removes every Unicode space. Pandoc breaks
a line at a newline alone and deletes a carriage return wherever it stands, so `found\rit.`
prints as `foundit.`. So `We found it.`, a form feed and three backticks opened a listing to
the gates that pandoc never made, and every gate stopped reading at it. A YAML block in
there escaped the `rule-opens-a-block` refusal, and its `title:` replaced paper.yaml's.

Asking pandoc about every fence line turned up more of the same. Pandoc closes a fence on up
to three spaces, the run, and nothing after it but spaces and tabs; a tab or a no-break
space in front, or a no-break space after, makes a line inside the listing, where the gates
closed on it and paired their next fence with the one after it, taking the prose between.
Pandoc opens one on an optional language word and an optional `{attributes}`, then spaces
and tabs, or a raw `{=format}`. A word ends at Haskell's idea of a space, which takes in
the no-break space and U+3000 but not U+0085 or U+2028, and holds no backtick or brace. The
attributes are `#id`, `.class`, `key=value` and `-`, read in that order, the first that
fits kept; a class and a key start with a letter as `str.isalpha` has it, the Unicode
categories of Haskell's `isAlpha`, where `\w` would have taken a superscript digit for one.

That much is read. The rest was modelled once and review found it wrong eight ways, the
worst new: `{r setup}`, an R Markdown chunk header, opens nothing in pandoc, which prints
the chunk as inline code running to its closer; the gates, rejecting the opener as pandoc
does, took the closer for an opener and read to the next chunk, hiding the prose between.
Pandoc also opens a backtick fence under a line of text but not a tilde one or an indented
one, and reads attributes on over lines while none is blank. So a fence is read only in its
plain form, a listing opened at the margin under a blank line, the first line or another
listing's closer, outside any comment or raw block, with its word and attributes on the
opening line, and closed; any other line starting with three backticks or tildes, behind
up to three spaces, behind a list marker, or behind whitespace other than spaces or a
zero-width mark, is refused (`unclear-fence`), by `check` and by the build, and `audit
--strict` fails on one in a Markdown paper. The second
review found why the margin: in a list item pandoc takes the item's indentation off before
it looks for the closer, and closed a listing the gates read on through the prose after it;
and why raw blocks: inside a comment, a `<pre>` or a TeX environment a fence is raw text to
pandoc, which the gates paired with a later one. A comment or raw block is taken as open
from its opening to its closing mark, outside listings, so an arrow `-->` in a Mermaid
listing refuses nothing. A listing a comment holds whole, with no `-->` on its lines, so
that the comment closes after its closer, is the comment's and is not refused: pandoc
prints none of it where it sees the comment, and the gates mask both. The review of the
sixth round's fixes found it refused, and a listing commented out while an author decided
failed `check` and the build, `--skip-checks` too, where #65 built it. The comment is the
gates' reading, which a stray backtick fools, so such a listing must also be one pandoc
reads as the gates do if the comment is not there: opened at the margin, and apart from
the line above, or a backtick fence straight under the `<!--` line, itself apart. Let be in
a list item, behind a comment only the gates saw, it was code to the gates up to the last
closer, ended early for pandoc, and the claim after it printed unread (the second round of
review of those fixes). Let be under any line of text, a backtick fence under a
footnote's line or a longer list item's was taken into the note or the item by pandoc and
ended at an indented closer, with the same result (the third round). Past three spaces pandoc
reads indented code or a list item's listing, and the gates read the lines as text: its
numbers are read, the safe side, but a `<!--` in it is read as a comment's, and hides the
prose after it up to the next `-->`, as the sixth review found (see the comment gap in
Known gaps). Refused on purpose, though pandoc opens them: a fence straight under a
heading, a list item's text, a `:::` line or a comment, and a line of text that opens with
backticks. `tests/test_pandoc_agreement.py` asks pandoc about 128 fenced shapes: the old
reader got 63 wrong; now 120 agree, the 8 that do not are refused, and 65 are refused in
all.

Raw blocks come in more shapes than a refusal can list (a `\newcommand` group, an HTML
attribute over blank lines), so the build compares too (`build/reading.py`, beside the
metadata and the headings): every listing the gates read in the sources must be, where it
stands, a code block pandoc makes, or a raw block for `{=format}`. A line of its own is put
first in each listing of the copy pandoc reads, and must come back once, first in its
block, and each listing is paired in order with the one the gates read in the source files,
at the same index in the same file with its values put in. Its lines must be the lines as
written, each placeholder standing for text within its own line: compared built to built
alone, a value holding a fence ended a listing early and the lines after it printed as
prose (the sixth review). The third review found why position and not lines: a listing the
gates read inside a TeX group, masking the claim after it, passed for a copy of its lines
in an indented block, and a comment holding them did as well, pandoc making every comment a
raw block. The fourth found why that line is made new each build: fixed, it could be typed,
and a copy of it in a listing pandoc did make passed for the one it did not. The sixth
found the line itself changing the reading: a caption over a listing opening with dashes
is a table to pandoc, and a line put first made it a code block, so the metadata and
headings after it went unread. The metadata and headings are read from the text without
the lines, and the reading with them must be that reading once they are taken off. A
listing `check` lets be because a comment holds it whole may come back inside a comment
pandoc reads, once, instead of opening a code block: the comment is the gates' reading of
where comments are, which a stray backtick can fool, and a listing in a comment pandoc does
not see must still be code. Code pandoc makes that the gates read as prose, an indented
listing, is not refused.

In `check`, a comment or raw block closes only on its own mark: a `-->` closed a `<pre>`,
and `\end{center}` a comment. One of the same name opened inside it is counted, as pandoc
counts it, except a `<script>`, which pandoc does not count; and `<?` followed by a letter,
`<?php` or `<?xml`, opens raw text to `?>`, where `<? marks a query` is text (the fifth
review found both refusing listings pandoc makes). Marks in a code span, `<pre-x>`, and
`<!-->` open nothing, and neither does a `<pre>` or `<?php` behind text on its line, though
pandoc does open one there when its closer follows (see Known gaps); a backtick behind a
backslash opens no span, and a line whose backticks do not pair blanks none, its span
perhaps closing on the next. The scans are linear: the widest closer still to come is read
from the end once, so an opener with none is passed over at once, where a run of narrowing
openers each used to read to the end; code spans are paired run by run in one pass, where a
pattern retried from every backtick of a run, and a line of 20,000 took seven seconds; and
every mark on a line is found in one pass, where a raw block's closer and another of its
name were searched for from each mark to the end of the line, and a line of 300,000
characters inside a `<pre>` took eighteen seconds (the fifth).

The manuscript is read with `read_text`, which makes a lone carriage return a newline
before the gates or the build see it; the reader agrees with pandoc either way. The front
matter is split with `splitlines` still, in the masking and in the build's title check, and
that is right: pandoc's YAML breaks a line at U+0085, U+2028 and U+2029 as well, and
refuses the document outright over a vertical tab, a form feed or U+001C.

## The digest chain did not survive a checkout

`.gitattributes` normalises what git stores. The digests were taken over what sits on disk.
Between those two facts, a project whose analysis writes CSVs on Windows recorded CRLF digests
for every declared input, and a fresh clone — on any platform, including the one the digests
were computed on — mismatched all of them.

Measured on the project that found it: **0 failing in the author's working copy, 35 failing in
a clone of the same commit**, every one of them `input-changed` on a file nobody had touched.
The `.gitattributes` had been added to prevent exactly this, and its comment records the
symptom it was written for. It made the input case certain instead, because it fixed the half
of the problem that was visible from inside the repository.

The fix is the one `source_digest` already applied to scripts, extended to the data an analysis
READS: hash the content, not the line endings, for suffixes where a line ending is formatting
(`.csv .tsv .json .yaml .md .bib` and the rest of `_DATA_SUFFIXES`). Everything else stays
byte-exact, because in a `.xlsx` or a `.zip` a CR is content.

Three decisions worth recording:

- **The fragment's own digest is still byte-exact, and must stay that way.** It is a
  cross-language contract — an R-written fragment and a Python-written one have to describe the
  same file the same way — and "hash the bytes you just wrote" is the only operation meaning
  the same thing in every language. An input is different: nobody reproduces it, they check it
  has not changed.
- **Checking tries the file's actual bytes first, then every canonical spelling.** The first
  version tried only the canonical three — all-LF, all-CRLF, all-CR — and that was a
  regression, not a fix: a file with MIXED endings, which is what you get from appending CRLF
  rows to an LF header, matches none of them, so untouched inputs that had been passing began
  to fail. Including the raw bytes makes the old behaviour a floor: nothing that passed before
  can fail now. A file whose *content* changed matches no candidate.

- **The suffix list is narrower than it first was, and the boundary is a judgement.**
  Normalisation rewrites every CR in the stream, not only the ones ending lines, so any format
  that can carry a CR *inside a value* would collide two different contents. `.sql` and `.txt`
  were listed and were removed on that ground — a verified collision between two INSERT
  statements settled the first. The same argument applies to `.csv`, whose quoted fields can
  contain a bare CR, and `.csv` stays: it is the format the entire problem is about, and
  excluding it would leave the gate broken for the ordinary case. That asymmetry is recorded
  rather than hidden.

- **UTF-16 with a BOM is never normalised.** There 0x0D and 0x0A appear as bytes of ordinary
  characters, so rewriting them corrupts text rather than reformatting it: U+340D and U+340A
  become the same file. A BOM settles it cheaply; without one, see Known gaps. Excel's
  "Unicode Text" export and many Japanese-Windows CSV exports are UTF-16, so this is in the
  path of the projects the toolkit is for.
- **Both emitters moved together, and there is now a test that says so.** `mg_input_digest`
  mirrors `input_digest`. There was no such test when this first shipped, and the R side
  consequently crashed on any text-suffixed file containing a NUL byte — it converted to a
  string before normalising, which R refuses — so a UTF-16 CSV that `digest::digest(file=)`
  had handled fine died inside the emitter. It now works on raw vectors. Ten cases,
  including embedded NULs, UTF-16 and the byte-exact `.txt` and `.sql`, are asserted
  byte-identical across the two languages.

## The skills, for an agent tool with no plugin

Claude Code and Codex install the skills as a plugin from this repository. Gemini CLI,
Mistral Vibe and Kimi Code CLI have no such route here. What they share, with Codex too, is a
folder: each reads skills from `.agents/skills` in a project and in the user's home. So
`manuscript-guard install-skills` copies the skills there (`--project` for the project you
are in, `--dir` for any other folder), and one command serves every such tool.

**One source.** The skills live in `plugin/skills` and nowhere else in the repository. The
wheel takes those files as `manuscript_guard/skills` when it is built (`force-include` in
`pyproject.toml`), and in a checkout `skillcopy.shipped()` returns `plugin/skills` itself. A
copy kept under `src/` would have been a second source. Three tests hold this: the package
directory has no `skills/`, a wheel built in the test carries every file of `plugin/skills`
byte for byte, and CI's wheel job compares the wheel's file list with what git tracks.

**The copy is exact, and so are its names.** A skill is copied as it is, under its own name:
the Agent Skills specification wants a skill's name to be its folder's, and the gates' hints
name the skills. Prefixing them would have meant rewriting each file on the way out, and the
copy would no longer be the source.

**Nothing that is not this tool's is touched.** The folder in the user's home is shared with
every other skill they have. Each copy leaves a stamp beside the skills,
`.manuscript-guard.json`, with the release and a digest of every file. A later copy replaces
a skill only if the stamp lists it and its files still have those digests, and removes one
that a newer release dropped on the same condition. A folder the stamp does not list, one
edited since, a link or a junction, or a file where a folder should be, is left as it is and
named, with what can be done about it, and the command exits 1. This is the rule the round
trip settled on: refuse rather than guess.

The stamp says which folders may be removed, so it is believed whole or not at all. A name
in it is used as a path: one that is not a single lower-case folder name (a path with `..`,
an absolute one, an upper-case twin of a real skill, which on Windows is the same folder)
makes the whole stamp unreadable, as do another schema, a missing field and broken JSON. And
a stamp that is there and unreadable stops the command before it writes anything, the stamp
included. It may be a later release's, and a new stamp over it would make every folder there
someone else's for good.

**A skill that is already there is not written again.** A folder that holds the text of the
skill that is coming is left as it is and recorded, whatever the stamp says of it. Writing
it again changed nothing in the text and did harm around it: a folder of the user's own with
the same text was written over, a copy with the line endings git gave it showed every file
as modified, and a folder in use was emptied. So a run with nothing to change writes
nothing but the stamp.

**A copy that stops half-way is finished by the next.** The stamp is written last. A skill
that does have to change is copied into a folder made for the purpose beside it, what stood
in its place is moved aside whole, and the copy is moved in; nothing is removed file by
file, and nothing that was already there is touched to make room. A folder that cannot be
moved, as one that is some program's working directory cannot be on Windows, stops the
command with the skill whole. Where the copy cannot be moved in, what was moved aside is
moved back. So after a copy that stopped, a file held open or an interrupt, each skill is
either as the old stamp describes it or as this release has it, and the next run takes
both. One skill can be missing instead: where the interrupt fell between the two moves, or
where the move back failed as well. What is gone then is a copy this tool made, and the next
run writes the skill.

**The digests are of the text, not of the bytes.** CRLF is read as LF. A copy committed with
a project and checked out by git on Windows comes back with the other line endings; with
digests of the bytes all fourteen read as changed, and stayed so for good.

**A copy goes stale, and the gates' own commands say so.** `pip install --upgrade` renews
the tool and leaves the copy. A hook could say so, and these tools run none of ours. What
every agent runs, under any tool, is `check` and `build`: after either, a stamp from another
release gets one line on stderr with the command that renews it, or, where the copy is the
newer, the command that upgrades the tool. It is printed after the command has finished and
changes neither its output nor its exit code, and a stamp that cannot be read says nothing.
The gates themselves do not look at it: a stale skill is not a finding about the manuscript.

`MANUSCRIPT_GUARD_USER_SKILLS` names the user's folder where it is not `~/.agents/skills`.
The test suite sets it to a folder that does not exist, so that a run never reads the copy
of whoever is running it.

## Known gaps

Recorded because a gate whose limits are undocumented gets trusted beyond them.

- **The figure-caption style reads one convention and nothing else.** The paragraph after a
  figure is set in `Figure Caption` (10 pt against 12 pt) when its text opens "Figure 1.",
  "Figure 4:" or "Figure S1."; the stop or colon has to come right after the number, so that
  prose resuming under a figure ("Figure 1 shows ...", "Figure 2.5-fold higher ...") is left
  as prose. A no-break space between the word and the number is read as a space. The cost: a
  caption written "Fig. 1.", "Figure one." or with a chapter-style number ("Figure 1.1."), a
  caption separated from its figure by a comment, and a caption under an image that shares its
  paragraph with other text are all left at body size. A figure that carries pandoc's own caption
  (`![caption](path)`) keeps `Image Caption`, which the reference document does not size
  either, and a caption inside a block quotation takes `Figure Caption` in place of
  `Block Text` and so loses the quotation's indent. The style is added to the author's own
  `reference.docx` from pandoc's user data directory when there is one, and skipped when that
  file already defines `FigureCaption`; table captions are untouched.
- **G8 compares only values whose units agree.** A count of 56 and a share of 56.0% are two
  quantities, and keying on the unit is what tells them apart. The cost: one quantity emitted
  once with `unit="%"` and once with no unit, or with the unit spelt two ways ("percent" and
  "%", "years" and "y"), is no longer reported as written two ways.
- **A UTF-16 input without a BOM is normalised as if it were 8-bit text.** Its 0x0D and 0x0A
  bytes can belong to ordinary characters, so an edit that swaps one such character for
  another (U+4E0D for U+4E0A) can leave the digest unchanged and pass G1. Exports that write
  UTF-16 carry a BOM; a file without one is taken for 8-bit text.
- **Checking a declared input reads the whole file into memory.** Before input digests
  normalised line endings they were streamed; a 300 MB CSV now peaks at about 1.2 GB while G1
  checks it. The R emitter peaks at about twenty times the file (600 MB for a 28 MB CSV), since
  its line-ending masks are logical vectors of four bytes a byte. Large binary inputs are
  affected too, because the file is read before its suffix is tested.
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
- **The title in a manuscript's header is read by line, not as YAML.** The comparison with
  `paper.yaml` (`two-titles`) takes what stands after the first `title:` in the block, at
  any depth and on that line alone, less every quotation mark and apostrophe at either
  end, and sets it beside `paper.yaml`'s title as YAML gives that one. So it warns of two
  titles that agree where the header's has:
  - a comment after it;
  - an apostrophe doubled between single quotation marks (`'Crohn''s disease'`);
  - a quotation mark or a backslash escaped between double ones. `init` types a title with
    TeX into `paper.yaml` that way (`"IFN-$\\gamma$ release assays"`), so an author who
    makes the two agree by copying that line into the header keeps the warning;
  - a quotation mark or an apostrophe of its own at either end, quoted or not
    (`"Rethinking the 'obesity paradox'"`, `A study of "frailty"`);
  - a second line it runs on to, or a folded or literal block (`title: >`);
  - an author's `title: Dr` above it, or no title of its own under such an author;

  and where `paper.yaml`'s own title is a folded block, whose closing line break YAML
  keeps. And it says nothing of two that differ where the header's title begins on the
  line under its key, is written `title :` or `"title":`, is written twice, of which YAML
  keeps the last, has `paper.yaml`'s title as its first line and runs on to a second, or
  differs from it only by a mark of its own at either end (`the patients'` beside
  `the patients`). `init` types no header that the two
  readings take differently. It is a warning, the document prints `paper.yaml`'s title in
  each of these, and deleting the title from the header ends it. A supplementary file's
  own title is compared with the paper's as well, and warned of: nothing prints it, since
  the supplement's title is made from the paper's. Its hint says that, and does not say to
  make the two agree. Reading the header's title as YAML, as its abstract is read, is a
  change of its own (Basile, 2026-10-04).
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
- **A name or a unit typed with pandoc's subscript and superscript signs was an unbound
  number.** G2 cuts an atom at the punctuation round it, so `CO~2~` was `CO~2`, which no
  term matched: `HbA1c` is a built-in term and `HbA~1c~` was reported, a declared `CO2` did
  not cover `CO~2~`, and `kg/m^2^` was reported where `kg/m²` never was. What passed was
  `terms: ['CO~2']`, sign and all, or the character itself (found 2026-10-04). Now a
  name is matched against the terms, built in and declared, with the signs of its
  subscripts and superscripts taken out, and the hint of a name that is not declared
  says how to declare it, `terms: [CO2]`. And an exponent on a unit is read as the
  superscript character is, as typography: one digit, with a sign or none, between
  carets directly after one to three letters, which takes in `m^2^`, `mm^3^`, `s^-1^`,
  `R^2^` and `χ^2^`, and the letter in italics, `*R*^2^`. `10^6^` stays a number, as
  `10⁶` does by its `10`. There is no list of formulae or of units: the terms are the
  list for names, and the shape is the rule for exponents (Basile, 2026-10-04).
  A sign is one where pandoc reads one: closed by another, with no space between. A
  tilde nothing closes is printed as a tilde, and stands for "about" or for a range. The
  first version took every `~` and `^` out, and the number after such a tilde joined the
  letters before it: `pH~2` was `ph2`, which holds the built-in term `h2`, and a pH, an
  effect of `HR~2`, a rise of `increased~2-fold` and the end of `1 week~2 weeks` passed
  `check` and the build (found by the review of the change). And read without its signs,
  a name is matched only by terms that open a word: `risk^1^`, a citation's number, was
  `risk1`, which holds the term `k1`.
  Where it stops. The terms have to account for every digit, as before, so a count typed
  hard against a name (`HbA~1c~7.2`), between the signs (`^412^`) or before a subscript
  (`412~patients~`) is reported. The hint says how to declare a term only of what reads
  as a name: it opens with a letter, its digits are all in its subscripts and
  superscripts, and it is no word with digits alone in a superscript (`shown^12^`,
  `year^-1^`). A term is still found anywhere in an atom as it is written, so `H2O` is
  accepted by the built-in `h2`, as before, and so is `H~2~O`, where `h2` opens the word.
  A symbol with a subscript that makes a term is that term: `b~1~`, `d~2~`, `k~2~`. An
  exponent of two digits or more, and one on a word of four letters or more, is a number:
  `year^-1^` and `mmHg^-1^` are reported, and are typed with the superscript characters or
  declared. That is narrower than what is read for the characters themselves, on purpose:
  `shown^12^` is a citation's number typed by hand, and the caret is how it is typed. One
  digit after a word of one to three letters that is no unit, `it^2^`, `OR^3^`, `mg^7^`,
  is not read, as `it²` is not: a citation's number typed there is missed. The
  conventions still read the text with its signs in: `75th percentile` is a convention
  and `75^th^ percentile` is none, and under Methods `I² > 50%` is one where `I^2^ > 50%`
  leaves the 50% reported. Both allowances hold wherever the tokenizer and the classifier
  are used, and not only in a manuscript's text: in a figure's text, in `audit` and in a
  string value the analysis emits, where `^` and `~` are only characters, `m^2^` is no
  number either and a declared `CO2` covers `CO~2~`. Listed in
  `tests/data/exemptions.yaml` as `unit-exponent`, with the test that types a number in
  each of those shapes.
- **`conventions:` and `terms:` in `paper.yaml` are self-service.** A pattern of `\d+` with a
  `why` of "house style" disables G2, and `terms:` needs no justification at all. The gate
  is a tool for an author who wants it, not a control over one who does not — so this stays.
  What has changed is that it is no longer *invisible*: every run reports how many numbers
  the project's own rules accounted for, and which rules did it, as `project-exemption`
  (a warning past a quarter of the numbers in the manuscript). Self-service and silent are
  different things, and only the first was intended. A convention may be given a name,
  `id`, by which that report and `explain` cite it, as `project:<id>`; without one it is
  cited by the first 24 characters of its pattern (Basile, 2026-10-03). A name is text on
  one line with something in it besides spaces; another is the schema's finding, and the
  convention is not read. Two conventions given one name each exempt what they match and
  are counted under it together, as two whose patterns begin alike are. Before the review
  of #153 the second one's matches replaced the first's, under either kind of shared name,
  and a number the first was written for failed as unbound.
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
  them out as lists and quotations, where it had run them into paragraphs, and names the
  run-on paragraphs it carries as not compared, because no paragraph goes by their
  identifier now. Nothing is applied, and a current build sent out ends it. Lists and quotes are on the list by choice: a
  marker in front of one rewrote it, and a marker inside its first item would let `import`
  splice that item over the whole block (see "The round trip carries prose"). Comparing
  them needs an identifier per item and a merge that puts the list marker back, and neither
  exists.
- **Which blocks are paragraphs is decided by pattern, not by pandoc.** `tag` runs where
  pandoc may be absent, so it reproduces pandoc's rules — two spaces after "C." before it is
  a list, the inline HTML tags a paragraph may open with, what can interrupt a paragraph —
  and is checked against pandoc in `tests/test_pandoc_agreement.py`, which CI runs against
  the pandoc it installs and pins, 3.9.0.2. Where the patterns are unsure they leave a block
  unmarked, which costs a comparison and corrupts nothing. Known cases: a paragraph opening with a TeX command
  (`\noindent`), one holding a line of nothing but dashes and pipes, one starting "p. 12"
  (pandoc's abbreviation rule, not reproduced), and a paragraph whose unescaped braces do
  not pair. And the scan for raw content does not know where pandoc reads a `<!--`, a
  verbatim tag such as `<pre>`, or a `\begin{x}` inside something it closes first. Found
  so far: inline code, inline or display maths, `\verb|...|`, an indented code block, a
  fence written under a line of its block rather than after a blank one, a fence opening
  a list item on its marker's line, a fence in a block quote or indented four columns or
  more, a link's destination or title, an image's destination or title, an autolink, the
  attributes of a tag, a span, a heading, a div, a link, an image or a code span, a table
  cell, a list item, a block quote, a line block, a definition, a YAML block in the body
  and any value in the front matter. `<pre>`
  and `\begin` are misread in link text, an image's alt text, an inline note and a
  citation's locator too, and `<!--` and `<pre>` in a TeX command's argument. There the
  opener is taken for real. The paragraphs from the one holding it to the one holding its
  closer go unmarked, though pandoc prints them: the closer is the next `-->`, the tag's
  own end tag (`</pre>`, `</script>`), or the `\end{x}` matching it by name. With no closer
  later in the file, nothing is hidden. The document looks right; an edit made to one of
  those paragraphs in Word comes back listed as not compared, to be carried over by hand.
  For a `<!--` anywhere but inline code, a fence and the front matter, `check`'s comment
  scanner hides the text from the opener to the closer as well, and G2 reads no number
  there (see "The comment scanner knows code spans, fences and the front matter"). No way
  around it is given here: each tried, a fenced block, an empty comment after the opener,
  an escape, `%3C` or `&lt;`, fails or changes the printed words somewhere the others
  work, and the reviews of #97 list where. Raw TeX other than an environment is not
  followed across a blank line. When the blank line falls inside braces, the blocks either
  side are refused by the brace count, since `\footnote{One.\n\nTwo.}` is one paragraph
  to pandoc; a block wholly inside
  such a group, the middle of a `\newcommand` with two blank lines in its body, gets a
  marker, and pandoc drops raw TeX from the .docx so the identifier names nothing, which
  `import` already tolerates. When it falls inside an optional argument,
  `\cite[p.~5\n\nmore]{key}`, the braces pair on each side and both halves are marked:
  pandoc then prints the halves as literal text. The document shows it and `import` stays
  consistent with it, and counting brackets instead would refuse every paragraph quoting an
  interval such as `[0, 1)`. Every review round on these patterns found holes in the
  version before it,
  each by running pandoc on a construct the table did not yet hold, so the table is
  evidence for what is in it and no more. The HTML block tags are pandoc 3.9.0.2's, taken
  from its source; a later pandoc that takes another tag for a block marks a paragraph it
  splits, until the agreement test is run against it.
- **A caption or a definition is told from a paragraph by its opening alone.** A block
  opening `Table:`, `table:` or a colon is a caption beside a table. A line that is `: ` or
  `~ ` and text, or a colon or a tilde alone, makes a definition of a single line above it,
  with or without a blank line between; under a paragraph of two lines or more it is more of
  that paragraph, or a paragraph of its own after a blank line. The tagger sees one block at
  a time, so it leaves every block that opens so, or holds such a line second, without an
  identifier. The merge escapes any such opening a co-author types. A rewording that brings
  a kept `:` or `~` up to a paragraph's second line, by joining the lines above it, is
  refused by #69's check: the next build would give it no identifier. A paragraph written
  that way in the `.md` is never compared.
- **A brace an earlier version wrote back is half a pair now.** Before a `}` was escaped,
  `import` wrote a co-author's `{a, b}` as `\{a, b}`. Only unescaped braces count now, so
  such a paragraph has an unpaired `}` and no identifier: it builds as before, but an edit
  to it in Word is reported as not compared and not applied, so it can be edited only in
  the `.md`. Adding the missing backslash, `\{a, b\}`, gives it its identifier back.
- **A rewording that splits a brace pair across a number or citation is refused.** A brace
  from Word is written escaped, so where a rewording leaves a bare brace from the `.md` on
  one side of a number or citation and its partner comes back from Word - edited, moved or
  typed anew - or is deleted there, the braces no longer pair and the paragraph is refused
  and named. So is a brace typed in Word that pairs with nothing. `main` before #72 wrote a
  `}` from Word bare and merged many of these correctly, 212 of 4,174 in #72's round-3
  differential; written bare, a brace can complete what pandoc reads as attributes after a
  `]`, a link, an autolink or a value, and #90's three review rounds found each (see "The
  writer and the tagger have to read an opening the same way"). Braces inside code count
  too, though pandoc pairs none there. The edit is made in the `.md`.
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
  differently, a paragraph can be marked inside code, and the marker prints there, and a
  table under such a fence can go unfollowed. Every case found so far, an opener whose info
  string pandoc rejects (`python title="x"`, `{code-cell} ipython3`), a `~~~` straight under
  a paragraph line, a fence line inside an HTML comment, is refused by `check`
  (`unclear-fence`) or by the build's comparison of listings, so no document is built from
  one; the entry stands because `tag` still pairs fences itself.
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

- **The warning of two titles was shown by no command.** Assembling compares the title in a
  manuscript file's header with `paper.yaml`'s and makes a warning where they differ
  (`two-titles`). `build` and `submit` printed what assembling found only when that held a
  failure, and `check` does not assemble, so the warning was made and nobody was told: with
  the title changed in `paper.yaml` and the header left as it was, `check` listed nothing
  and `build` printed the name of the document. That document carried `paper.yaml`'s title,
  the one meant, so nothing wrong was printed, while this file said the build warned. Found
  in the work on #162. `check` now gives the warning at every stage, from the gate that
  already refuses what assembling would refuse; the stage decides which failures are due,
  and a warning is not one. `build` and `submit` print what assembling warns of, once and
  before the document is made (Basile, 2026-10-04). `import` rebuilds a document already
  sent and says nothing of it, as before. How the header's title is read is as it was; its
  limits are above.
- **An abbreviated `--submission` was not seen by the submission guard.** argparse reads any
  prefix of an option that names one option only, so `manuscript-guard build --subm` was a
  submission build and `review --subm` a review at submission standard, and the guard's
  marker is the whole word: in a project that fails, `build --subm --offline` was let
  through by the guard. `build` then refused on its own account, as it does while anything
  fails; with `--skip-checks` it built, and that build is what the guard missed. Found in
  the review of #131 and true before it. No command reads an abbreviated
  option now (Basile, 2026-10-02): `build --subm` exits 2 with `unrecognized arguments:
  --subm`, and so does `--off` for `--offline`, which is the cost, paid by someone typing a
  short form by hand. No document, skill or test in the repository wrote one. The marker was
  not widened to the prefixes instead, because it would then have to be kept in step with
  the parser by hand: on `review`, `--su` already stands for `--summary` as much as for
  `--submission`. argparse's setting belongs to each parser, and on the top one alone it
  leaves every command abbreviating, so it is set by the class the commands are made from.
  `tests/test_cli.py` takes the commands that have the option from the parser and holds
  every prefix of the word to one rule, that a spelling read as a submission is one the
  guard's pattern matches; a second test fails for a command added with abbreviations on.
  Before any command, `manuscript-guard --vers` is an error too, though the message is
  argparse's for the missing command and does not name the option.
- **A backslash before raw markup was not read.** `<!--`, `\begin{x}` or `<pre>` after an
  odd number of backslashes is text to pandoc, and `import` writes what a co-author types
  in Word so: a `<!--` typed there comes back as `\<!--`. `_blocks` took it for an opener
  all the same, and where a `-->` followed further down the file, that paragraph and every
  one up to the `-->` went without an identifier. A co-author's next edit to them was
  dropped with "nothing came back"; since #69, `import` refused the rewording that typed the
  `<!--` instead, though it was safe to make. A `\<div>` in a paragraph did the same to that
  paragraph alone. An opener, a LaTeX `\begin` or `\end` and a block-level tag now count
  only where no backslash escapes them (`_backslashed`): an odd run makes them text, an
  even one escapes itself. Inside a comment or a verbatim element pandoc reads no escapes,
  so `\-->` and `\</pre>` still close them. Braces were left to #72, which merged with this:
  `_untagged` counts only unescaped braces, and `import` escapes a `}` as well as a `{`, so a
  lone `{` typed in Word, written `\{`, keeps its paragraph's identifier, and so does
  `\{\{results.x\}\}`, a binding typed as text (see "The writer and the tagger have to read
  an opening the same way").
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
- **A value printing display maths split its paragraph in Word.** Identifiers are given to
  the source before bindings are substituted, and a paragraph with `$$` in its source gets
  none. `em.value("model.formula", "$$y = 2.1 x$$")`, bound in the sentence that ends a
  section, put `$$` into a paragraph that had one. Pandoc gave the equation a Word paragraph
  of its own, and only the part before it carried the identifier. A co-author who swapped
  that part with the paragraph above had the whole sentence moved in the .md, exit 0, and
  `check` said nothing: the digit kept even the prose warning quiet. G2 now refuses a value
  whose display holds what, typed into the source, would have kept the identifier off the
  paragraph (display maths, a LaTeX environment or an HTML block tag), and a line break,
  after which a blank line, a fence or a `<div>` ends the paragraph. Leaving such a
  paragraph untagged was the other way, and it was not taken: the identifiers would then
  depend on the results as well as the source, and `import` reads them from the source.
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
- **A PDF is read as its reader gives it, less a short table of foldings.** Curly quotes,
  the dashes, the hyphens U+2010 and U+2011, the ellipsis and the ligatures fi, fl, ff, ffi
  and ffl are folded before a quote is looked for. Anything else one reader spells out and
  another does not is compared as it comes: a quote typed with "oe" is not found in a source
  read as "œ". A quote copied from the source, which is what the hint asks for, is.
- **An ellipsis set against a value hides it.** The ellipsis is folded to three full stops
  and a value is not read with a full stop before it, so a quote holding `…14 per 100 000`
  does not state 14 and is reported `value-not-in-quote`. With a space after the ellipsis
  it does.
- **A minus sign in a PDF figure is not the hyphen in its sidecar.** A figure saved as PDF
  with its text kept as text (matplotlib's `pdf.fonttype: 42`) holds U+2212 before a negative
  tick, and a sidecar entry `"-1.0"` does not allow it: `figure-number-unbound`. Poppler's
  `pdftotext` always read it so; the one from Xpdf wrote a hyphen until it was asked for
  UTF-8 and now reads it the same. The entry has to hold the sign the figure does.
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
- **A plain record is not checked against where it is filed.** A named reading must say
  the reader, the reviewer and the round its place says. `<reviewer>.yaml` is read as it
  always was: its `reviewer` and `round` fields are not compared with its place, so a
  record copied from round one into round two counts there if its digests still match.
  Left alone so that no existing record starts failing. It answers for no named reader.
- **A reading the panel does not name is not counted.** A file put beside a record by
  hand, or one whose reader was taken out of the panel, is not opened: its findings, major
  ones included, bind nobody, and the only sign is the `reading-unnamed` warning. Taking a
  reader out of the panel is how a reader who will not report is released, and it is also
  how a reading that did report can be set aside; the panel file's history shows which.
  The alternative was to guess from a file's contents whether it is a reading, and two
  review rounds each found a guess that let a reading drop out with no warning it could
  be told from.
- **Two readers of one remit whose names share their letters and digits cannot both be
  asked.** `model.a` and `model-a` both file as `model-a`; a panel that lists both for one
  reviewer is `duplicate-reader` until one is renamed. Names that differ only in case, or
  in characters that are neither letters, digits nor their marks, are one reader.
- **A reader's name is compared as it is composed, and not otherwise folded.** A full-width
  letter and its ordinary form, a digit of another script and the same digit in ASCII, or
  `ß` and `ss`, are different readers.
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
- **What a provider does with a manuscript it is sent is outside the toolkit.** Retention,
  logging, human review and training on inputs are set by each provider's terms and by the
  account the key belongs to. The dry run and the statement before a run say what leaves the
  machine and for which host; they cannot say what happens to it there. Blinding has the
  same edge: each request is a new conversation that carries nothing from an earlier round,
  but a provider that keeps a memory across requests is not something a request can see.
- **A provider's reviewer does not see the figures.** A request is text. Each figure's place
  is marked, and a caption the author wrote beside it goes with the prose around it, but
  the picture is not sent, so a model's reading says nothing about whether a figure shows
  what the text claims. G10's figure review is still the check on that.
- **A provider that is not built in may name any other environment variable as its key.**
  A built-in provider's variable is refused, but nothing can list every variable that
  holds a secret: `key_env: GITHUB_TOKEN` under a provider in a `paper.yaml` somebody else
  wrote would send that token to its host. The statement before a run names the host and
  the variable for every provider, which is the place to notice.
- **Taking a key out of a message can take a word with it.** Any four characters in a row
  that the key also holds are replaced, so a provider's message that happens to share four
  with the key loses them. Fewer than four of the key's characters in a row are not
  recognised as the key's.
- **A connection that cannot be opened in time reads as a timeout.** The client does not
  ask again after a timeout, because the request may have run and been billed. urllib does
  not say whether the time ran out before or after the request was sent, so a provider
  that was merely unreachable is not retried either, and the message says it may have
  been billed when it cannot have been.
- **A reviewer is sent the numbers as they print today.** Bindings are replaced with the
  current values in `results/` and the ledger. A record's digests cover the manuscript's
  source files, as a hand-filed record's do, so re-running the analysis after a reading
  changes what the paper says without marking that reading stale. `document_digest` closes
  this for a built document; nothing closes it for a review, by a person or by a model.
- **The journal profile and the checklist are sent whole.** They are the project's own
  files, comments included. A checklist generated from a guideline's published text is sent
  to the provider as part of the request, which is use rather than redistribution, but it
  does leave the machine with everything else.
- **The provider presets are a snapshot.** Base URLs, key variables and the spelling of an
  output cap were read from each vendor's documentation on 2026-10-02. A vendor that moves
  its endpoint breaks the preset until a release follows; `review.providers` takes the new
  URL under another name in the meantime. Google's endpoint documents neither a JSON mode
  nor an output cap, so neither is sent there, and `review.max_output_tokens` has no effect
  on it.
- **Plain http is taken for this machine only.** A model served over http from another
  machine on a laboratory network is refused, with or without a key, because the manuscript
  would cross that network unencrypted. Putting it behind https, or tunnelling it to
  localhost, is the way through.
- **A server on this machine that passes requests on is recognised only by Ollama's names.**
  A model whose name ends in `-cloud` or `:cloud` at an address on this machine is said to
  leave it through Ollama's servers, in the statement, the question and `review --providers`.
  Anything else at such an address is said to stay unless the server there passes it on:
  a cloud model Ollama names some other way, a proxy, a tunnel, or a llama.cpp or vLLM
  server that forwards what it receives, none of which the address or the name shows. A
  local server's model whose own name happens to end in `-cloud` is warned of needlessly.
- **The size of a request is an estimate and no price is shown.** The statement before a
  run counts the calls and gives the bytes of the largest request at four characters a
  token. Tokenisers differ by model and prices change, so neither is built in; a model that
  reasons before answering is billed for output the reply never shows.
- **`--yes` is whoever typed it.** The tool cannot tell an author's `--yes` from an
  agent's. Sending the manuscript is the author's decision, and under an agent that rests
  on the agent asking: the `review-panel` skill tells it to show the dry run and wait for
  the author's word, and nothing in the command can hold it to that.
- **A call that has been made cannot be recalled.** Ctrl+C stops further calls; the ones
  in flight, one for each provider at most, have left the machine, and the command waits
  for them, up to the ten minutes a call may take. A call a provider had asked to be
  tried again is not tried again after the stop. A second Ctrl+C ends the command with
  a traceback, and the process still stays until the calls in flight come back, and
  files their replies.
- **A refused reply is not asked for again by the run that got it.** The reply was paid
  for, the reason is printed, and the text is kept to read; asking again is running the
  command again, which is the author's call and asks only for what is missing. A model that
  answers the same way every time is taken out of `review.models` and out of the panel's
  `readers` by hand.
- **Part of a key shorter than twelve characters can reach a record, and a key shorter
  than eight is not looked for.** A review is refused for twelve of a key's characters in
  a row, not four as in a printed message. A key begins with its vendor's prefix, and at
  four every review that said `project` was refused for a key beginning `sk-proj-`. A
  server on the same machine is given a word for a key: `test` refused every review,
  since a record has a field called `rejection_tests`, and at eight `sk-no-key-required`
  refused each review that said `required`. What a provider says of itself is held to
  four, and a printed message has every run of four taken out.
- **Some readers of a panel do not hold its lock.** A writer rewriting a panel empties the
  file before filling it, and a reader in that instant finds it empty. `review --record`
  holds the lock of its own round's panel, but a reviewer who is not on it yet and is
  called without a remit has it looked up in the earlier rounds' panels, which are read
  without theirs, the latest that names the reviewer first. With that panel being
  rewritten at that moment, the call is refused for want of a remit, in words, and run
  again it files; but if an older panel names the reviewer too, the call files at once
  with that older round's remit, which the new panel then carries without a word. `review
  --run` builds its plan from the panel before it takes the lock, and a panel read empty
  there stops the run with "not a valid panel, so nothing is sent". G11 and `check` read
  panels with no lock at all, and can report an emptied one as malformed until the writer
  finishes. Each needs two writes at the same instant, and only the older remit is written
  down.
- **The panel's lock is a file, and a file can be left behind.** A writer that dies holding
  it stops the others for up to two minutes, after which the lock is taken as abandoned;
  the message names the file to delete sooner. Two writers that both find an abandoned lock
  at the same instant can each remove it, and the slower one may remove the faster one's
  new lock, after which both write the panel. It needs a crash and two writers within the
  same few milliseconds, and it costs what the lock was added to prevent: a reader missing
  from the panel, which `reading-unnamed` reports.
- **On a file system with no hard links a record is not written through a temporary
  file.** It is created exclusively, so an existing record is still never replaced, but a
  write that is cut short can leave part of a record, which G11 then reports as unreadable.
- **Two runs of one round at once are not prevented.** Each asks for every reading that
  is not on file, so each missing one is paid for twice. A record is never replaced: the
  second reply for a reading is refused as one that already exists, and kept under
  `refused/` to read. The lock that keeps one run's threads from taking that folder away
  from each other is the process's own; between two processes the write is tried again
  once in a folder made again.
- **A provider is asked one call at a time and there is no pacing beyond that.** A rate
  limit is waited out twice, as the provider's `Retry-After` says, and then the reading is
  left missing for the next run.
- **A panel that gains a reviewer or a reader is written again from its data.** Every field
  is kept and the YAML is laid out afresh, so a comment typed into a panel file is lost the
  next time `review --record` or `review --run` adds to it. The panel's `rationale` and each
  reviewer's `why` are fields, and are where its reasons belong.
- **A run asks the models listed now, not the readers the panel named before.** Take a
  model out of `review.models` after a run and its missing readings stay `reading-missing`
  until its name is taken out of the panel's `readers` as well. The command lists those
  readers and exits 1 for as long as the panel names them; it does not ask them, and it
  does not take them out.
- **A reply holding U+0085 is refused, not filed.** YAML reads that character back as a
  line break, so the record would not say what the model said. A model that writes one is
  rare; the reply is kept under `refused/` to read.
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
- **The hooks depend on `manuscript-guard-hook` being on PATH.** Installed in a virtualenv
  the editor does not share, they cannot run, which is the safe direction: nothing is blocked
  and nothing is guarded. It is not silent, going by the hooks documentation: a hook whose
  command exits with anything but 0 or 2 (a shell's 127, command not found) shows a
  non-blocking `hook error` notice in the transcript. Not observed in a live session.
- **The submission guard sees a command only through the tools it is registered for, and
  only the verbs it knows.** Those tools are `Bash`, `PowerShell` and `Monitor`. A command
  that an MCP server runs, a terminal tool for one, never reaches it, and neither does a copy
  made inside a script the agent runs. That the PowerShell tool sends its command in
  `tool_input.command` is taken from Claude Code's hooks reference, and it was then seen to
  hold. On 2026-10-03, in a session started after the plugin was updated, and in a copy of
  the example with its reviews deleted, `Write-Output 'Copy-Item build\manuscript.docx
  elsewhere'` through the PowerShell tool was refused, under `PreToolUse:PowerShell` and in
  the words the Bash tool's `echo 'cp build/manuscript.docx elsewhere'` was refused in. The
  event itself was not captured. For `Monitor` the field is taken from the tool's own input,
  which that reference does not describe, and no `Monitor` command was seen held or let
  through. Not held, in PowerShell: the
  aliases `cpi`, `mi` and `irm`, left out because so short a word before a `.docx` would be a
  false alarm more often than a submission (`irm`, the short name of `Invoke-RestMethod`, is
  also the French for MRI, and as a verb it had the guard refuse
  `manuscript-guard import returned-IRM.docx`); and a .NET call that names no verb the guard
  knows, such as `[IO.Compression.ZipFile]::CreateFromDirectory`. In any shell, the document
  has to be named after the verb, on the same line and within 120 characters of it. So a
  pipeline that names the document first is not held, and that is how PowerShell is usually
  written: `Get-ChildItem build\*.docx | Copy-Item -Destination D:\out`. Nor is a path put in
  a variable beforehand, a command continued onto a second line before the path, or a verb
  whose other arguments fill the 120 characters, which PowerShell's named parameters do
  sooner than a Unix command's: `Send-MailMessage` with `-From`, `-To`, `-Subject` and
  `-Body` written out before `-Attachments build\manuscript.docx` is let through. The false
  alarms are of the kind the guard already had: in a project that fails the submission
  check, `Invoke-WebRequest` saving a journal's template as a `.docx` is refused as
  `curl -o template.docx` is, and so are `robocopy` on a folder whose name has the word
  submission in it and `iwr` on a journal's `submission-guidelines` page. Under Codex the
  matcher is part of what a user trusted (`hook_hash` in
  `codex-rs/hooks/src/engine/discovery.rs`, read 2026-10-02), so after this change of
  matcher the guard is skipped there until the user reviews it again with `/hooks`.
- **`build --stage submission` is a submission build the submission guard does not hold.**
  `--stage submission` gives the same verdict as `--submission` and is not one of the
  guard's markers, which is why a refusal can name `check --stage submission`. On `build` it
  is let through too: in a project that fails, `manuscript-guard build --stage submission
  --offline` is not stopped by the guard and refuses on its own account, and with
  `--skip-checks` it writes `manuscript.UNCHECKED.docx`, where the same command with
  `--submission` is refused before it runs. Found in the review of #136 on 2026-10-02 and
  true on `main` before it. Not decided: a marker for `--stage submission` after `build`
  only would close it.
- **Under another name the command line is not a submission the guard sees.** The marker for
  the pack is the words `manuscript-guard submit`. The package installs `mguard` as a second
  name for the same command, and `mguard submit --offline --skip-checks`, `python -m
  manuscript_guard.cli submit` and `manuscript-guard.exe submit` are all let through in a
  project that fails. `submit` refuses on its own account without `--skip-checks`. An option
  is seen under any name: `mguard build --submission` is refused. Found in the review of
  #136 and true on `main` before it. Not fixed yet; the marker's line is one #132 changes.
- **`AGENTS.md` is read by some agent tools and not by others, and it is written once.**
  Read from each tool's documentation on 2026-10-02, none of it observed in a session: Codex
  reads it before any work, from the repository's root down to the working directory, up to
  32 KiB in all; Mistral Vibe reads it in a folder the user has trusted; Claude Code from
  2.1.277 reads it only where there is no `CLAUDE.md` in the working directory or above;
  Gemini CLI reads `GEMINI.md` and takes `AGENTS.md` only once `context.fileName` in its
  settings lists it; for Kimi Code CLI a third-party page says it is read and Kimi's own
  documentation was not found to. The file is written by `init` and never again: a project
  made by an earlier release has none until `init` is run on it once more, a later release's
  wording does not reach a file already written, and it says `results/` and `build/` even
  where `paths:` in `paper.yaml` has moved them. A file that names the toolkit anywhere is
  taken to hold the rules, so one that mentions it and lacks them gets no notice. Its first
  rule says a checklist profile is written by `transcribe` from a recipe, which is untrue of
  one file: the worked example's `DEMO-OBS.yaml` is invented and written by hand, and has no
  recipe.
- **Under Codex the hooks are tested against its source, not in a session.** The handlers are
  tested with payloads shaped as `codex-rs` builds them and patches that follow its grammar,
  as read on 2026-10-02. No hook has been seen to fire in a live Codex session, which needs a
  login. What Codex itself does not enforce: a hook is skipped until the user reviews and
  trusts it with `/hooks`, and again after its definition changes; the write guard sees a
  patch, not a file written by a shell command, as under Claude Code; and Codex's hooks page
  says that some tool paths can opt out and calls tool hooks "a useful guardrail, not a
  complete enforcement boundary". If Codex changes the envelope's markers, `patch_paths`
  reads no file from it and the write guard guards nothing, in silence; `check` still reports
  an edited results file afterwards. A patch Codex would reject as malformed after its first
  header can be refused by the guard first, which costs nothing, since it would not have been
  applied. Codex also applies a patch that a model sends as a shell command
  (`apply_patch <<'EOF'`). Whether a hook then sees it as a patch or as a shell command was not
  established from the sources read; if as a shell command, the write guard does not read it.
  The reader was compared with a Python port of Codex's parser on generated patches, by the
  reviewer of the pull request, and not with the parser itself. After a patch, an analysis
  script that was changed and moved out of `analysis/` gets no reminder, since it is read
  where it now is; and a file updated by one hunk and moved away by a later one is still
  named where it no longer is.
- **On Windows every hook misread a name outside ASCII.** The event was read from standard
  input as text, which on Windows is the system's ANSI code page, what Python gives a pipe,
  and not the console's (so `chcp 65001` changed nothing), and the tools write it as UTF-8
  without escapes. Under code page 1252 the note after an edit said nothing for
  `manuscript/méthodes.md`, a refusal named `results/donnÃ©es.json`, and a results directory
  moved by `paths:` to `résultats` was not guarded. A project kept anywhere under an accented
  folder, and a home folder named after its owner is enough, had no hook at all: the write
  guard found no project above the file, and the session start and the submission guard none
  at their `cwd`. Under code page 932 a name in Japanese was misread in the same way, and
  where it named a folder the whole event could be lost: the last byte of `語` begins a
  two-byte character there and takes the backslash that follows it, and what is left is not
  JSON. Found by the reviewer of #124 on 2026-10-02 with bytes piped by hand, and seen the
  same day in a session of Claude Code 2.1.286: the installed hook gave its note for
  `methods.md` and none for `méthodes.md`, written one after the other. With `PYTHONUTF8=1`
  set the name was read. Closed: the event is read as bytes and decoded as UTF-8 (see "A
  hook reads its event as UTF-8"), and the tests start the hook as a tool does, on an edit
  from Claude Code and on a patch from Codex, with neither `PYTHONUTF8` nor
  `PYTHONIOENCODING` set, and once more with standard input forced into a code page so that
  they fail on every platform if the reading comes back. What is known of the tools: a
  `SessionStart` event of Claude Code 2.1.119, kept
  by a hook that wrote its input to a file, holds the folder `thèse` with the two bytes
  `c3 a8`. Codex was not run, which needs a login; its source builds each event with
  `serde_json::to_string`, which escapes nothing outside ASCII, and writes those bytes to the
  hook (`codex-rs/hooks/src/events/` and `engine/command_runner.rs`, read 2026-10-02 at
  8a400e78). Still open: an event in
  an encoding that is neither UTF-8 nor the one standard input has loses its letters outside
  ASCII. Lost from the file's own name, the write guard still refuses, by folder and
  extension and under a garbled name, and the note after an edit finds no file. Lost from a
  folder above the project, or from a results directory moved by `paths:`, the file is not
  guarded, as it was not before. Where Python opens standard input with `surrogateescape`,
  as it does on Windows and under the C locale, a byte the encoding cannot read used to
  become a lone surrogate and is now U+FFFD. On Windows that is another garbled name. Under
  the C locale the surrogate named a file whose name on disk is not UTF-8, and U+FFFD names
  none. A text in a code page that happens to be valid UTF-8 is read as UTF-8. And a name
  sent in one Unicode normal form and written in `paper.yaml` or on disk in another was not
  tried; macOS is where that would show.
- **The submission guard said nothing about a project it could not read.** Where
  `check --submission` stops on an error of the project's own, a results file that is not
  JSON for one, the gates raise before there is a finding. The hook took that for an
  unexpected failure, exited 0 in silence, and the command went through. The session start
  was silent there for the same reason. Found in the review of #130 on 2026-10-02 and true
  before it. Closed the same day, by the author's decision: the guard refuses with the
  project's own sentence, which names the file, and the session start says that sentence in
  place of the status line and blocks nothing (see "A hook never breaks the session"). The
  files concerned are the ones read before any gate runs: `paper.yaml`, `authors.yaml`, the
  results fragments and the two ledgers under `literature/`. A file that a gate reads was
  never part of this, since a gate that raises is reported as `gate-errored`, which fails at
  every stage. Where no project is found at the folder the event names, or above it, both
  hooks stayed silent, as before: a command sent from above a project that enters it, `cd
  paper && manuscript-guard submit`, was not checked, in a project that fails as in one that
  cannot be read. True on `main` before this and found in the review of #131. The submission
  guard has since been given the projects such a command names, and refuses for one that
  cannot be read in the same words; the session start still says nothing from there. The
  refusal ends by naming
  `manuscript-guard check --stage submission` and not `check --submission`, whose flag is
  one of the guard's own markers: an agent told to run that one is refused again. It says
  to run it on its own, because the command ends in the word `submission`, which the guard
  matches after `cp` or `git push` on the same line. The older refusal, for a failing check,
  says the same since #131.
  The hooks pass on that one error and no other, so `check` has to raise it for everything
  of the project's own that stops it, and it did not. A file among those that was not UTF-8
  ended `check` in a traceback (`UnicodeDecodeError`), and so did a `paper.yaml` that held a
  list (`AttributeError`). There the guard was silent as it had been, and the command went
  through. Looking for more of the kind found these: a `paper.yaml` that held text or a
  number, and text is what YAML makes of `title:My paper` with no space after the colon;
  `paths` that was not folders by name, or one folder given as a number or left empty; a
  file the system would not open;
  a `stage` that is not one, `draft` for `drafting`, on a plain `check` (with `--submission`
  the stage is given, so the check ran and reported the line); and, from the review of the
  change, a date that does not exist, typed without quotes. `verified_on: 2026-09-31` is a
  date to YAML until the date is made, and that fails with an error that is not one of the
  parser's own, so it went past the two that were caught. Each is now said in a sentence
  that names the file, and `check` exits 2. For a file that is not UTF-8 the sentence gives
  the encoding where a byte-order mark names it, else the byte and the line it is on, and
  says to save the file as UTF-8. For the others it gives what the file holds and what was
  expected in its place, the stages to choose from, or what the parser said. The submission
  guard refuses with the sentence and has not changed. Such a file is refused and not read
  in the encoding its mark names, which is how the audit reads an output it was handed:
  these are the project's own files, and one way to write them leaves less to get wrong than
  five. Refusing on any error at all would have covered all of it and was not chosen: a
  fault of the tool would then stop every command that names a `.docx` in that project, with
  a message its author can do nothing with. Two things are refused that were not. A
  `paper.yaml` that holds `[]`, `0` or `false` was read as no settings, with the schema's
  findings for everything missing, and is now refused like any other list, number or yes or
  no. And a
  folder under `paths` that only a gate asks for, given as a number, was a schema finding
  beside a `gate-errored` one and now stops the check before any gate. The write guard did
  change, by one name. It asks `paper.yaml` where the results are kept, and it caught the
  error a file that is not UTF-8 used to raise, so it went on under the usual names. The new
  error went past it: the guard ended in silence and the edit went through, which the review
  found. It catches that error now, and so guards `results/` and `build/` under their usual
  names in a project whose `paper.yaml` does not parse as well, where it had always been
  silent. A folder moved by `paths:` it cannot know there. A file a gate reads is still a
  `gate-errored` finding. Where what the gate raised is this error, the finding now carries
  its sentence with no class name in front, under a hint that no longer begins with a bug in
  the tool: a review record in UTF-16 read "UnicodeDecodeError: 'utf-8' codec can't decode
  byte 0xff in position 0" and named no file. A manuscript file that is not UTF-8 was not
  covered by that, since the gates read it themselves: `check` gave seven `gate-errored`
  findings for one file, one for each gate that read it, none naming it, and `explain`,
  `render`, `bind`, `methods`, `sync-bib` and a build with `--skip-checks` ended in a
  traceback. Closed the same day, by the author's decision. Every gate that reads the
  manuscript's text, and each of those commands, goes through the reader the project's
  files use, so those commands say the sentence and exit 2. `check` reports one finding for each such file,
  `manuscript-unreadable`, at the file and the line, and its hint names the gates that stopped
  there. It does not stop before the gates, as it does for a project file: the gates that
  do not read the manuscript still report, `--json` carries the finding, and the line drawn
  above holds, that a file read before any gate stops the check and a file a gate reads is
  a finding. Seven findings that each named the file would have been the smaller change,
  and they take seven of the eight lines the submission guard shows. Every manuscript file
  is read once before the gates, since a gate stops at the first file it cannot read: left
  to the gates, a second file went unnamed until the first was put right. A gate that meets
  such a file does not go on to the files it can read, because a word count, or the list of
  results nothing quotes, taken from part of the manuscript is wrong in ways that would be
  findings of their own. The file is refused and not read in the encoding it seems to be
  in, for the reason given above. What is read of a file that is UTF-8 has not changed:
  line endings are folded as they were, and a mark at the top of the file stays in the
  text. Three readers are left as they were. G11 reads the file's bytes for the digest and
  still runs, so at submission the records of the earlier text are reported stale beside
  the finding. The note after an edit reads with the bytes it cannot decode replaced,
  since it is a note and gives no verdict. And the dry run of a review panel, `review --run
  --dry-run`, which came with #128, decodes the files it would send by itself: it says
  "manuscript/main.md is not UTF-8, so it cannot be sent as text" and exits 2, which names
  the file and gives neither the byte and the line nor the encoding.
  A key of `paper.yaml` that only a gate reads, in a shape the schema refuses (`terms: 5`,
  `review: [1]`, `conventions: abc`, `reporting_guideline: 5`), was a `gate-errored`
  finding worded as a fault of the tool, "G2 could not run: TypeError: 'int' object is not
  iterable", beside the schema's own finding, which names the key; `explain` and `bind`
  ended in a traceback on `terms: 5`. Closed with it, by the same decision: a gate reads of
  such a key what the schema accepts, of a list or of the settings under `review` the
  entries it accepts, and runs as if the rest were not set. The schema's finding fails at
  every stage, so no project passes that failed. For what exempts, that is the stricter
  reading: an entry of `conventions` or `terms` that is not read exempts nothing, so until
  the key is put right the numbers it accounted for are reported as unbound beside the
  schema's finding. For `rounds_required` it is the default, two, and that can be fewer
  than was meant: `"3"` in quotes was read as three. `review` on its own does not print the
  schema's findings, so there the command answers for two rounds; `check` fails on the
  schema's finding either way. The rounds asked for are still read beside a mistyped key
  under `review`. A convention whose pattern is not a regular expression is text to the
  schema, and raised where the classifier is built ("G2 could not run: error: unterminated
  character set at position 0"). It is now a finding that names the entry, under the
  schema's code, and the entry is not read. It is made where the project is loaded, before
  any gate, so whatever the compiler raises is caught: the review found a pattern,
  `(?a)(?u)x`, whose error was not the compiler's own, and which ended every command in a
  traceback and the hooks in silence. A convention with an `id`, by which the classifier
  names the rule, was refused by the schema, so a project that wrote one failed already,
  and with this change it was not read either. The schema allows `id` since (Basile,
  2026-10-03), and a named convention is read and cited by its name. The build reads
  `keywords` with no gate in front of it under `--skip-checks`. It raised on `keywords: 5`,
  which is not printed now. One word where a list is expected was printed letter by letter,
  then for a day not at all; it is printed whole, as the one keyword (Basile, 2026-10-03).
  An entry of the list that is not text is printed as it was, `2019` for one, which YAML
  reads as a number, and so are keywords typed with colons where the dashes belong, which
  YAML reads as settings: a build that was asked not to check prints what was typed. What
  it prints, pandoc reads as Markdown, as it reads the text: `*E. coli*` is set in italics
  in a title and loses its asterisks in the document's properties, and
  TeX outside `$`, `TNF\alpha`, would be left out, which is a finding since (below). The
  review of #153 found that the title, the
  short title and the keywords were written into the build's YAML header by hand, between
  double quotation marks. A `"` in one ended the string and the build stopped, and a
  backslash began an escape: `$\alpha$-synuclein` became the control character 7, which the
  document carried in its properties and Word would not open. A keyword or a title the
  schema accepts did this through `check` and a checked build, which made it a false pass,
  older than #135. They are written as JSON strings now, whose escapes are YAML's, with
  their lines folded into one first, as YAML folded them between hand-written quotation
  marks: written as JSON, a blank line in a title made it two paragraphs, and the Word
  writer left the title out. And a control character is refused, by `check` as a finding
  at the key and by the build in a sentence. One comes from an escape in `paper.yaml`
  itself: `"\alpha-blockers"` between double quotation marks is U+0007 and `lpha-blockers`.
  Pandoc had refused it in the hand-written header, and written as JSON's escape it reached
  the document. Both were found in the second round of the review. The check of that fix
  found that a line split also takes the vertical tab, the form feed and three
  separators for the end of a line, which YAML does not: `\v` and `\f` begin TeX's
  `\varepsilon` and `\frac`, and folded into a space they lost the letter after them
  through `check` and the build. Only what YAML reads as the end of a line is folded, the
  tab is kept, and any other control character is refused. So are a surrogate, half of a
  pair that two `\u` escapes make where they are written as JSON writes a character past
  U+FFFF, and U+FFFE and U+FFFF, which are no character: `check` passed them, the build
  ended in a traceback on a surrogate, which cannot be written as UTF-8, and in pandoc's
  words on the other two. And the break a value closes with is taken off, not folded: a
  block ends with one, and as a space it stood after `al.`, where pandoc reads a space as
  a no-break space, so a title written as a block was printed with one after it. These
  came from the last check of #153.
  A fourth note from that check was a choice, which the author made (Basile, 2026-10-03).
  Between double quotation marks YAML reads `\n`, `\r`, `\t`, `\N`, `\L` and `\P` as the end of
  a line or a tab. No refusal of characters reaches those, since a title may hold a line
  break: `"The $\nu$ frequency"` was printed `The $ u$ frequency`, and `\rho`, `\tau`,
  `\Lambda` and `\Pi` lost a letter the same way, through `check` and the build. `check`
  now reads `paper.yaml` as it is written. One of those six escapes directly before a
  letter, in a title, a short title or a keyword that stands between double quotation
  marks, is a finding at the key that fails at every stage, and a build that skips the
  check refuses it in the same words. Between single quotation marks, with none, in a
  block, or with the backslash doubled, the letter is kept and nothing is found. What the
  finding does not reach: an escape before a space or a digit, which takes no letter; a
  letter outside A to Z; the no-break space `\_`, and an escape written as a number,
  `\x0a`; a title or a keyword that comes into the file by a merge key (`<<`); and the
  other text of a project that a document prints, the names in `authors.yaml` for one.
  Nor the title page of a pack made with `submit --skip-checks --document`: it is handed
  a document built elsewhere, and prints the title as YAML read it. A line break meant as
  one and written `"First\nsecond"` is a finding all the same. It costs a space in its
  place, which is what the build printed for it, and the finding says to write a space
  there: a backslash kept where no TeX was meant is TeX to pandoc, which drops the word
  after it. `import` builds the source again to compare the returned document with, and
  makes that build without the refusal, so that a document sent before it existed can
  still come back; `check` and the next build refuse the title all the same. And `init`
  types the title it is given into `paper.yaml` as a JSON string, where it typed
  quotation marks around it as it stood: a backslash in it was an escape the author never
  wrote, and a quotation mark in it left a project that could not be read. The header it
  types into `manuscript/main.md` cannot take that form: the build reads that title by
  taking what stands after `title:` and stripping the quotation marks around it, to compare
  it with `paper.yaml`'s. So the header holds the title between the quotation marks under
  which pandoc and that reading both give it back as it is: double ones, as always, for an
  ordinary title; single ones for a title holding a backslash or a double quotation mark;
  and where neither does, the header is left out and
  `paper.yaml`'s is the only title. That is a title holding both kinds, and one that
  begins or ends with a quotation mark of either kind, `the patients'` for one, since the
  build's reading strips every one of them at either end; for one that begins or ends
  with an apostrophe the header had read as another title.
  Before that, a title with TeX or a
  quotation in it left a new project that failed `check` on a header the author had not
  typed. TeX that stands outside `$` was the next thing found: `IFN-\gamma release
  assays` went into both files as given, passed `check`, and was printed `IFN-release
  assays`, as any title was where its backslash is a backslash. The header `init` typed
  used to fail on most such titles, which hid that. It is a finding since (Basile,
  2026-10-03): see the next paragraph.
  A title holding a character no document can carry, a control character, a lone
  surrogate, U+FFFE or U+FFFF, is refused before anything is made. A lone surrogate,
  which Python makes of an argument that is not in the terminal's encoding, ended `init`
  in a traceback and left an empty `paper.yaml` that a second `init` kept; the others
  made a project `check` failed or could not read. A tab or a line break in a title
  given to `init` is written as a space, which is what the build prints for each: as its
  escape, a tab before a letter was reported as a letter lost. A value is
  read from its own opening quotation mark, and of a key written twice the one YAML keeps
  is read: a comment after an anchor was taken for the value, and both of two titles for
  the title. These came from the review of the change.
  Pandoc reads a backslash directly before a letter as TeX wherever it stands, and the
  Word writer keeps TeX only as maths, between dollar signs. A command takes what follows
  it as TeX would: `12 \pm 3 months` is printed without its `3`, and `\textit{in vivo}`
  without its words. In a title, a short title or a keyword that is a finding at the key
  that fails at every stage (Basile, 2026-10-03), in these words: `\gamma` stands outside
  dollar signs, and the document is printed without it; if it is maths, write
  `$\gamma$`. A build that
  skips the check refuses it in the same words, `init` refuses such a title before it
  makes anything, and `import` builds a document that was sent without the refusal, as
  for a lost letter.
  `check` runs without pandoc, so the rule is a model of pandoc's reading of one line
  (`text/tex.py`). It is meant never to pass a value that pandoc drops TeX from, and to
  report one that pandoc keeps only in the places listed below. `tests/test_tex.py`
  holds it to the pandoc CI pins, on tables and on 4,000 random lines. Each part of it
  came from a line it would otherwise pass:
  a `$` opens maths only as pandoc opens it, so `x$ \gamma $y` and `$\gamma$5` hold
  none; a backtick, `<`, `[` or `@` can hold a `$` that opens nothing, in code, a tag, a
  link's address or a citation key; pandoc reads a subscript or a superscript on its
  own, with its escapes read once already, so maths cannot run past its end and a
  doubled backslash in it is one, and `~a\\gamma~` loses its `\gamma`; it resolves
  the character references in one as well, once more for each script around it, and
  leaves a carriage return out as it reads, so `^&bsol;gamma^`, `^~&amp;bsol;gamma~^`
  and `^&bsol;&#13;gamma^` each lose a `\gamma`; and a letter is any letter, `\étude`
  too, by pandoc's Unicode, which may be newer than Python's: 622 letters of Unicode
  15.1 were none to Python 3.12, so a code point Python has no name for is taken for a
  letter after a backslash. The third came from random lines tried against pandoc
  while the rule was written, and the last two from the review of the change, whose two
  rounds put 52 million lines of their own making to pandoc. The references are not
  resolved here. That was the fix for the first round, and the second found two values
  it passed, a script in a script and the carriage return. So a character reference
  in what a subscript or a superscript can hold, from a `~` or a `^` to the next space,
  is itself the finding, whatever it stands for and however deep the scripts: none
  exists without a typed `&` and a `;` after it.
  Where it reports what pandoc keeps: past a backtick, `<`, `[` or `@` no maths is
  read, so every backslash before a letter is reported from there to the end of the
  value, in maths, in code, or doubled (`[18F]FDG and TGF-$\beta$` is one); from a `~`
  or a `^` to the next space the same holds, and to the end of the value where that
  stretch holds a `$`; a character reference in such a stretch, `x^&alpha;^` for one,
  which pandoc prints, and with it any `&` there that a `;` follows, since it is not
  read to see whether it is one; a command pandoc cannot read as TeX, which it prints
  as typed, a
  brace after it never closed, a `%` between its braces, `\end` with no `\begin`; one in
  a value pandoc reads as code, `>` and a tab before it; a backslash before a code
  point that is no letter in any Unicode yet; and one before a letter that Python's
  Unicode has and pandoc's has not, 4,302 letters of Unicode 16.0 on Python 3.14 with
  pandoc 3.9. No title or keyword of the example or of the one manuscript this was
  tried on holds a backslash, so neither says how often an over-report occurs.
  The finding's sentence is held to being true of the value it is printed for, and its
  remedy to working, which each round of the review found it was not somewhere. Past a
  sign it does not say "outside dollar signs": it names the sign, says the document may
  be printed without the command, and says to put a backslash before a sign that is
  only itself, `\[18F\]FDG`, or to type the character, and with that the value passes.
  After a `$` that opens no maths it says why, for every command up to the next `$`:
  `TGF-$\beta$1` is printed `TGF-$$1` and `$p \leq$0.05` loses its `\leq`, for the
  digit after that `$`; and after maths that a dollar amount earlier in the title opens,
  it says so, and that `\$` is a dollar sign that is only one. Where braces follow the
  command it does not say to write the command between dollar signs, since
  `$\textit${in vivo}` is printed as typed. Where none follow it says "if it is
  maths", since a path is none. A keyword is told to write it as text, the character
  itself for a letter: it is printed in the document's properties only, where pandoc
  writes maths as its TeX. And an `&` that a `;` follows, where a subscript or a
  superscript can hold it, is told that it may be a character reference, and to be the
  character it stands for or, where it stands after the script, to stand after a
  space (before the `&` of `x^&alpha;^` a space would end the superscript, and pandoc
  print its carets): the rule does not read it to see
  whether it is one, and `R^2^&RMSE; model fit` holds none (the last check of the
  change found it told "is a character reference in a subscript or a superscript").
  What the finding does not reach: the other text of a project that a document prints,
  the names in `authors.yaml` for one; the title page of a pack made with
  `submit --skip-checks --document`; a pandoc that reads a line otherwise than the one
  CI pins; maths in a title or a keyword as the document's properties carry it, which
  is as its TeX, `IFN-\gamma release assays` for a title whose page shows the letter;
  a code span the author marks `{=latex}`, which that mark leaves out of the document,
  and which is reported only where it holds a backslash before a letter; and a
  backslash before a sign, which is the sign: `10\,mg` is printed `10,mg`
  where TeX's thin space was meant, in a title and in the text alike.
  Nor the manuscript's text, which was a false pass: `\approx
  {{results.cohort.n_reports}}` in the example's Results passed `check` and the build,
  and the document was printed without the number (found 2026-10-03). Every gate had
  counted the number as printed. The build refuses it since (Basile, the same day). It
  asks pandoc how it reads the text before it makes the document, with the values put
  in, so what pandoc reads there as TeX outside maths is in hand and exact, wherever it
  stands: a citation's brackets too, where pandoc keeps what stands before and after
  the key apart from the rest and the first version did not look (the review of the
  change moved the sentence there, and the number was lost again), and the description
  of an image that stands in a figure's caption, which was passed over with the
  figure's own image, whose description is the caption a second time. The refusal names
  the first piece and counts the rest. It holds at every stage and under
  `--skip-checks`, and the document from the build before is removed with it, as for a
  misread heading. `check` read the sources and still passed such a text. A rule that
  reads the sources could only over-report: what pandoc takes for TeX turns on
  citations, brackets, `<`, line breaks and the values put in. So `check` asks pandoc
  too (Basile, 2026-10-04), where pandoc is on PATH: one run for the paper and one for
  its supplement, on the text the build would hand it, under the header of an offline
  build. What it reports is what the build refuses, in the build's sentence, as
  `tex-in-the-text`, failing from `drafting` on, and the build's warning of a layout
  command with it, each at the file and the line the sentence names. Pieces that read
  the same are one finding, at the first place, which counts the others, so that every
  kind is named in one run; twenty kinds are named and the rest counted, as for the
  warning. The build's refusal now says that `check` reports it too.
  What `check` does not reach here. Without pandoc on PATH it judges none of this and
  passes, with one note (`tex-not-judged`, severity `info`, and
  `documents_read_for_tex` at 0): a run in CI with no pandoc passes a text the build
  would refuse, and the build cannot run there either. Before `drafting` the finding is
  listed and does not fail, where the build refuses at every stage. A text pandoc
  cannot read, or one nested too deep for its reading to be walked, is a note too, and
  the build says the rest. So is a pandoc on PATH that cannot be run, and an answer
  from it that is no JSON. It costs `check` two runs of pandoc, about a fifth of a
  second on the example, and at most ten seconds each: pandoc takes about three times
  as long for each level of brackets nested in brackets, a quarter of a second at six
  deep and thirteen at ten, and the first version of the rule waited for it without
  limit, so that `check` did not come back on a line of brackets (found by the review of
  the change, on the suite's own prose: `check` had never waited on another program).
  Past ten seconds pandoc is stopped and that document is not judged, which is said
  in a note; pandoc reads 164,000 words of ordinary prose in two. The build gives
  pandoc no limit, as before, and on such a text it waits as long as pandoc takes. And
  the finding
  is pandoc's reading, so it changes with pandoc's version, as the build's refusal does.
  What the build lets pass: maths, code and a comment, which are no TeX to pandoc; TeX
  the author marked as raw for LaTeX, `{=latex}`, which pandoc labels `latex` where it
  labels unmarked TeX `tex`; and a macro's definition (`\newcommand`, `\renewcommand`,
  `\providecommand`, `\def`, `\DeclareMathOperator`, each with its braces), which
  prints nothing and which pandoc applies in maths. Marked `{=latex}` a definition is
  no longer applied, and `$\RR$` stays `\RR`, so the build's remedy for one is not the
  mark. The macro used outside maths is refused. What the refusal says to do is a code
  span marked `{=latex}`, and not a block: a block so marked passes the build, and G2
  fails any raw block from `drafting` on (`raw-block`), as it did before this change.
  TeX that is nothing but layout commands is a warning and the document is made
  (Basile, 2026-10-03): it prints no word in LaTeX either, a manuscript holding one
  built before the refusal, and the round trip and its skill speak of a bare
  `\newpage` as an ordinary thing. The warning says it does nothing in a Word document,
  marked or not, and gives the page break as a code span of Word's own in a paragraph
  of its own, `` `<w:r><w:br w:type="page"/></w:r>`{=openxml} ``, which passes `check`
  and breaks the page. The commands are a list, kept in one place (`text/tex.py`), and
  no more than a list:
  `\newpage`, `\clearpage`, `\cleardoublepage`, `\bigskip`, `\medskip`,
  `\smallskip`, `\vfill`, `\hfill` and `\noindent`; `\pagebreak`,
  `\nopagebreak`, `\linebreak` and `\nolinebreak`, with a number from 0 to 4 in
  brackets or none; `\vspace` and `\hspace` with a length in braces. A length is a
  number with a unit (`pt`, `pc`, `in`, `bp`, `cm`, `mm`, `dd`, `cc`, `sp`, `em`, `ex`,
  `mu`), one of thirteen commands that are lengths (`\baselineskip`,
  `\bigskipamount`, `\columnwidth`, `\fill`, `\linewidth`, `\medskipamount`,
  `\paperheight`, `\paperwidth`, `\parindent`, `\parskip`, `\smallskipamount`,
  `\textheight`, `\textwidth`) or a number of times one, with a sign before it or
  none (`\vspace{-\baselineskip}`), and after it what it
  stretches by and shrinks by, `plus` and `minus`, once each and in that order.
  `\hspace{412}` is no length and is refused. So is `\hspace{412\patients}`: a
  number before any command passed for a length at first, and `We enrolled
  \hspace{ {{results.n}}\patients} patients` passed `check`, was warned of, and was
  printed without its number (found by the review of the change). A definition and a
  layout command that pandoc reads as one piece, one directly over the other, are a
  warning too, which names the layout command and not the definition. A layout
  command that is not on the list is refused: `\centering`,
  `\raggedright`, `\par`, `\quad`, `\newline`, `\label{...}`, `\FloatBarrier`,
  `\newpage*`, `\pagebreak [4]` with a space before its bracket, and a length that
  LaTeX takes and that is not in the form above: one given by a command with braces
  of its own, `\vspace{\stretch{1}}`, or by a length command that is not among the
  thirteen, `\vspace{\topsep}`; `\vspace{1,5cm}` with a comma for the point,
  `\vspace{1EM}` in capitals, `\vspace{- 1em}` with a space after the sign,
  `\vspace{1em plus1pt}` with none after `plus`, `\vspace{1 true cm}` and
  `\vspace{\dimexpr 1em\relax}`. So is one that takes
  something with it: pandoc folds digits that open the next line into a command that
  takes no braces, so `\newpage` over `412 reports` is TeX that holds the 412, and
  `\newpage[412]` and `\newpage{412 patients}` are each one piece of TeX. Up to
  twenty kinds are each warned of, and the rest are counted.
  What the refusal does not reach, and where it is wrong about what it refuses:
  a build that does not ask pandoc for its reading, which is `import`'s build of a
  document that was sent, so that one sent before the refusal can still come back, and
  the annotated copy. TeX marked `{=tex}`, which pandoc labels as it labels unmarked
  TeX, and which is refused, where `{=latex}` passes. A definition in a form that is
  not read, which pandoc applies and the build refuses: `\let`, `\gdef`,
  `\global\def`, `\DeclareRobustCommand`, and a
  `\newcommand` whose body has no braces or whose name is spaced in its braces; the
  refusal says to write it as a `\newcommand` with its braces, and does not say to
  mark it. It says so only of a piece that opens with such a definition: a definition
  that is read, with a number under it that the piece takes, was told to be written as
  it already was. And `\newenvironment`, which is refused as well and which no
  `\newcommand` can be, is told what any TeX is told. A macro that leaves out the text it is given and comes to a layout command
  or to a definition, `\newcommand{\brk}[1]{\newpage}` and `\brk{412}`, which
  is warned of or passed, and loses the 412. The place named, which is not always
  where pandoc read the piece as TeX. The piece is looked for in the text as built,
  where it stands with its value, and the line is that of the same occurrence of its
  command in the file: `\approx` before a bound number is found where it stands, and
  not at a `$\approx$` further up, where the first version sent the author. But a
  piece that reads the same as text in maths or in a code span above it, a bare
  `\gamma` under a `$\gamma$`, is found at the first; a command the file's own header
  holds, which the build takes off, is counted from below the header; and a macro's
  expansion is found in its definition. TeX that only the
  text as built holds is said to be put there by a value or a table, with the file's
  name and no line. And G2, which reads the sources and holds every digit to being
  bound, fails `\vspace{1em}` and the `[2]` of a definition with two arguments from
  `drafting` on, as it did before, so a length with a digit in it is warned of only
  before that stage or under `--skip-checks`.
  Whether a keyword should be printed as typed, with its asterisks and backslashes, rather
  than read as Markdown, is not decided; it would differ only in the document's properties.
  Still open, and each fails at every stage, so none is a pass. A file a gate reads by
  another route keeps the older wording: a figure's `.guard.yaml`, `methods.lock`. So does a
  folder under `manuscript/` named like a source, `notes.md`: the gates that read text name
  it, but G11 reads bytes for the digest and reports "PermissionError", and `review` ends
  in a traceback on it, as before, with or without the dry run of a panel. And a
  results fragment with the mark of UTF-8 in front,
  which Notepad's "UTF-8 with BOM" writes, is refused in the parser's words ("Unexpected
  UTF-8 BOM (decode using utf-8-sig)"), where YAML with that mark is read. Two more are of
  the hooks, in a project whose `paper.yaml` parses and is refused for the shape of one
  entry under `paths`, and were found in the review of #134. The write guard does not know
  a folder that another entry moves: with `results: output` beside a `figures:` left empty,
  an edit under `output/` goes through. It was refused before an entry in the wrong shape
  stopped the whole file being read: the guard now keeps to the usual names there. `check`
  exits 2 until the entry is put right, and G1 reports the edit after that. And the note
  after an edit says nothing in such a project, where it named the unbound number. Both
  were known when #134 merged, and neither is closed.
- **Where the hooks run, an agent cannot run `check --submission` in a project that fails
  it.** The submission guard matches `--submission` anywhere in a shell command, so it holds
  `manuscript-guard check --submission`, `review --submission` and `respond --submission` to
  the submission check as it holds a copy of the `.docx`, though the first two only read. Its
  refusal says to run `manuscript-guard check --stage submission` on its own, which it does
  not match. With an action verb before it on the same line it does, because the command
  ends in the word `submission` and no spelling the documents give avoids the word:
  `git push && manuscript-guard check --stage submission` is refused, and so is the check
  after `cp a b &&` or after `cd "example - Copy" &&`, where the folder's name is the verb.
  On the line after such a command it goes through. `review` and `respond` take no `--stage`:
  in a failing project an agent sees the review at submission standard through `check
  --stage submission`, and `respond --submission` waits until the check passes. The README,
  the submission-pack and review-panel skills, and the `MANIFEST.yaml` of a pack assembled
  with `--skip-checks` still write `check --submission`, which costs an agent one refusal
  before it is told the other spelling. Letting a command through when it is a `check` and
  nothing else was considered and left (Basile, 2026-10-02): the rule has to tell
  `manuscript-guard check --submission` from the same words followed by `&& scp`, and a
  mistake in it lets a submission through, which is what the guard exists to stop. An author
  typing in a terminal is not affected, since a hook sees only the agent's commands.
- **From a folder with no project, the submission guard finds only a project the command
  spells out.** It used to find none. It matched the command, then ran the submission check
  in the folder the event names as the agent's, and from the folder above a project there is
  no `paper.yaml` to find: the check could not run and the hook said nothing. From there
  `cd example && manuscript-guard submit`, `manuscript-guard submit example` and `scp
  example/build/manuscript.docx host:` all went through, in a project that fails. `submit`
  then refused on its own account; the copy was held to nothing. Found in the review of #131
  on 2026-10-02 and true before it. Closed for a project the command names (see "The command
  is held to the project at the agent's folder, or to the one it names"). What is left:
  - *Not spelt out, so not found.* A folder held in a variable (`cd $PAPER && manuscript-guard
    submit`, `scp $PWD/example/build/manuscript.docx host:`), a glob that stands for the
    folder (`scp */build/*.docx host:`; one for the file, `example/build/*.docx`, is found),
    an option with its value joined on (`tar -Cexample -czf submission.tgz .`,
    `Copy-Item -Path:example/build/manuscript.docx`), a command inside a quoted string
    (`bash -c "cd example && manuscript-guard submit"`, `python -c "..."`), and a folder
    whose name is only partly in quotes (`my" "paper`). A folder with a comma or a brace in
    its name is found in quotes and not without them (`cd Smith,\ Jones`), since a word
    ends at either. Three ways curl names a file: quoted inside its own quotes (`-F
    'file=@"example/build/manuscript.docx"'`), a list in braces inside quotes (`-T
    "{a.docx,b.docx}"`), and after `<` (`-F "file=<example/manuscript/main.md"`). And a
    path as PowerShell writes it that ends in a backslash before the next argument,
    `Copy-Item .\example\ sent/submission -Recurse`: a backslash and a space are read as a
    space in a name. Without the backslash at the end it is found, on Windows. These go
    through as before.
  - *Not looked at, or looked at in the wrong place.* A folder on another machine written
    `//host/share/...` is not looked at: asking whether it exists waits for the host, and
    the hook fires on a shell command. The same share under a drive letter is looked at,
    and waits if the host does. In Git Bash `/tmp/x` is the user's own temporary folder;
    the guard reads it as `\tmp\x` on the drive the agent is on, so a project kept under
    the one is not found and one under the other would be taken for it.
  - *Inside a project, only that project.* Where the agent's folder is in a project the
    guard checks that one, as it always did, and does not read the words: from a project
    that passes, `cd ../second && manuscript-guard submit` is let through though `second`
    fails. Not decided.
  - *A commit that stages a file of the paper is refused when its message reads as a
    submission.* `git add paper/manuscript/main.md && git commit -m "copy-edit the abstract
    before submission"`, sent from the folder above, is refused in a project that fails:
    the markers match the message, a verb and then the word, and the staged path names the
    project. Nothing leaves the machine. Inside the project the same commit was always
    refused; from above it used to go through, and so did `git add paper && git commit -m
    "..." && git push origin submission-v2`. The message alone, with no path, names nothing
    and goes through. The remedy is in the markers, which should not read a verb inside a
    quoted string, and is not this change's. Found in the review of #137.
  - *A word that is the folder's name is taken for the folder.* With the paper in `paper/`,
    `git push origin paper  # submission` from the folder above is held to it, though the
    word is a branch. So is `Paper` on Windows, which ignores case, `paper.` there too,
    since Windows drops a dot or a space at the end of a name, and the end of
    `https://example.org/dl?f=paper`, since a word ends at `=`, at a comma and at a brace.
    So is what follows the last `@` of any word and the last `=` of a quoted one, which
    are read for curl's sake: `mail -s "submission" editor@paper`, and a commit message
    that ends `p=paper` or `thanks @paper`. And on Windows a file called `paper (1).docx`,
    written `cp paper\ \(1\).docx /backup`: a word ends at a bracket, escaped or not, and
    Windows drops the space left at the end of `paper `. In quotes it names nothing.
    A copy into the project, `cp ~/Downloads/edited.docx paper/`, is held to it too, as it
    always was from inside (the word-roundtrip skill says to give the path to `import`).
  - *The check a refusal names can be refused in two shapes.* Written with the folder last
    it is let through whatever the folders are called, unless the path itself reads as a
    submission, a verb and then the word: `copy/my submission/paper`. And an agent that
    enters the folder on the same line instead, `cd paper-copy && manuscript-guard check
    --stage submission`, puts the verb before the word: that line now names the project
    and is refused, where it used to go through unchecked. The folder is written in double
    quotes, where a shell expands `$`: for a project in `big$money/` the check named finds
    no project.
  - *The session start says nothing from the folder above*, in a project that fails or in
    one that cannot be read.
  - *A long command costs a look on disk for each different word.* 2000 of them took 1.3 s
    and 20,000 took 12 s on a busy machine. It is paid only by a submission-shaped command
    sent from a folder with no project, such as a long script written into a file through
    the shell that holds a verb and `.docx`.
  - *Two limits of the markers met on the way, true in any folder and before this.* `git -C
    example push` is not submission-shaped: `git push` is matched as two words side by
    side. And a `.docx` more than 120 characters after its verb is not matched, which a
    whole path can exceed.
- **An installed plugin is a copy, and goes stale silently.** The repository is its own
  marketplace (`.claude-plugin/marketplace.json`), and `claude plugin install` copies the
  plugin into Claude Code's cache. A skill corrected in the repository reaches nobody until
  they run `claude plugin update`, and nothing tells them to. An update compares only the
  version in `plugin.json` and the marketplace entry: a skill edited without a bump is
  reported as "already at the latest version" and never reaches anyone. Verified 2026-09-24
  with Claude Code 2.1.119.
- **Codex installs the plugin from Claude Code's manifests, and only the install has been
  seen.** Codex reads `.claude-plugin/marketplace.json` and `plugin/.claude-plugin/plugin.json`
  (its documentation calls the first a legacy-compatible marketplace), so the repository has
  no manifest of Codex's own and no second copy of the skills. Seen on 2026-10-02 with Codex
  0.158.0-alpha.2.1 on Windows, with no login and a scratch `CODEX_HOME`, from a checkout and
  from GitHub: `codex plugin marketplace add`, then `codex plugin add`, end with the plugin
  listed as installed and enabled at the manifest's version and every file of `plugin/`
  copied. `codex plugin marketplace upgrade` then took the copy installed from GitHub from
  0.2.320 to 0.2.370 when `main` moved, with no second command; a marketplace added from a
  local path has no upgrade ("is not configured as a Git marketplace"). Codex's program also
  carries an automatic upgrade of marketplaces. When it runs was not established, since the
  `codex plugin` commands do not start it, so the plugin may move ahead of the pip package
  unasked, which is what the stale-tool notice is for. CI's `codex-plugin` job repeats the
  install on each pull request, from the checkout and not through GitHub, against 0.160.0
  and the latest release. When a release of Codex changes its listing, its cache layout or a
  command, the `latest` leg goes red on every open pull request, whatever that pull request
  changes: the thing to do then is to read what changed and move the test and the pinned
  release, not to look for the fault in the pull request. Not seen, because it needs a
  login: a session in which a skill loads, a hook is trusted or a hook fires, and so whether
  Codex gives a plugin's hooks `CLAUDE_PLUGIN_ROOT`, as its documentation says and as the
  stale-tool notice needs. If Codex stops reading Claude Code's manifests, the CI job fails,
  and the plugin then needs manifests of Codex's own (`.codex-plugin/plugin.json` and
  `.agents/plugins/marketplace.json`). The install needs the `codex` command, which the
  desktop app on its own may not put on `PATH`.
- **The package and the plugin are one release with one number.** `pyproject.toml`,
  `manuscript_guard.__version__`, `plugin.json` and the marketplace entry carry the same
  version. The policy (Basile, 2026-10-02) is that a pull request leaves the version line in
  each of the four as `main` has it, and the coordinating session raises the number on `main`
  after merges that change `src/` or `plugin/`. Its bump is the one pull request that changes
  those lines, and it changes nothing else. From 2026-09-30 until then every pull request
  that changed `src/` or `plugin/` took the next shared number and bumped all four, with the
  numbers assigned so that two open pull requests never took one. With a dozen open at once
  two branches carried the same number all the same, which git merges without a conflict and
  which was caught before either merged, and `main` passed the number of a pull request that
  was waiting for its review. `tests/test_version.py` fails when the four differ. It cannot
  tell that code changed on `main` and the number was not raised after it, which is the case
  the policy is for: `pip install --upgrade` finds nothing newer for a fix under the old
  number, and the stale-tool notice below cannot fire either, because `plugin.json` did not
  move. Between a merge and the bump that follows it, `main` is in that state. The README's
  `--force-reinstall` is the fallback. Before the package and the plugin had one number,
  the package sat at 0.1.0 while the plugin moved, so `pip install --upgrade git+...` found
  nothing newer and left an older copy in place, and `--version` could not say which release
  anyone had. Verified 2026-09-30 with pip 26.2: an upgrade takes a newer commit when its
  version rose, and does not when it did not. `pipx upgrade` never takes one from a git
  install ("no package index was checked"); `pipx install --force git+...` does.
- **A stale command line tool is warned about, not prevented, and only from 0.2.260 on.**
  Skills and the tool update separately, so the plugin can be newer than the installed tool.
  The session-start hook compares the plugin's version (read from
  `$CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json`) with the tool's and says so once, with the
  upgrade command, and blocks nothing. It says nothing when the variable is unset, the file
  is unreadable, or the version is not plain dotted digits. The comparison lives in the
  tool's own handler, so a tool older than 0.2.260, which is every copy installed before it,
  runs the old handler and never warns: its first upgrade has to be made by hand, as the
  README says. Making the check from the plugin's `hooks.json` instead would reach them,
  since that updates with the plugin. Not observed in a live Claude Code session. The
  plugins reference lists `CLAUDE_PLUGIN_ROOT` among the variables exported to a hook's
  process, and the hooks reference describes `systemMessage` as a field any hook event can
  return, shown to the user as a warning. The same JSON carries `additionalContext`, so the
  model is told either way. The reverse, a tool newer than its plugin, is silent, and so is
  a plugin never updated: nothing tells anyone to run `claude plugin update`.
- **The skills are worded for any agent tool, and the test that keeps them so knows a list.**
  The skills are in the open SKILL.md format, which other agent tools read as well as Claude
  Code. `tests/test_plugin.py` fails when a skill names an agent tool (Claude, Codex, Gemini
  CLI, Mistral Vibe, Kimi Code), a tool only one of them has, a plugin, the words "slash
  command", `/manuscript-guard:`, one tool's instruction file, its `.claude` directory, a
  `CLAUDE_` variable or an `mcp__` tool name, and when its frontmatter carries a field the
  Agent Skills specification does not define. The `AGENTS.md` that `init` writes is held to
  the same scan. It
  matches on spelling, so it errs both ways. A tool that is not on the list passes, as does a
  command typed as `/project-setup`, and wording that assumes one tool without naming it,
  such as a step only that tool can carry out. ChatGPT, Copilot and Cursor are left off
  because a skill may name them as subject matter (where a pasted artefact came from, what a
  co-author used in Word), and model providers because a review panel may name where its
  models come from; any of them used to mean the reader passes too. In the other direction, a
  short list of phrases is taken out before the scan: Zotero's, Better BibTeX's, Word's or a
  browser's plugin, a plug-in estimator or principle, "Anthropic's Claude" unless "Code"
  follows, "Claude
  Opus", "Claude Sonnet", "Claude Haiku", "Claude models" and a hyphenated model name ending
  in "-Codex". Claude or Codex named in prose any other way fails ("Claude" alone in a list
  of models, "Claude 4.5 Sonnet", "the Claude family") and has to be written as an
  identifier; other model families pass however they are written. A reader addressed by one
  of the phrases taken out ("if you are Claude Opus") passes, since a pattern cannot tell that
  from a member of a panel. Another product's plugin named in a way that is not listed fails
  ("the LibreOffice plugin"). Where a skill describes
  a hook it says "where the hooks run", since an agent tool may have none. Read under Claude
  Code only so far: no skill has been followed in a session of another tool.
- **The audit cannot tell where a number should be, only whether it exists somewhere.** A
  value correct in the abstract and wrong in the Results passes, as does a number matching
  a coincidental value in an unrelated output. It is triage for existing work, not a
  guarantee.
- **A copy of the skills is found stale in two places only, and by two commands.**
  `install-skills` leaves a stamp, and `check` and `build` name a copy whose stamp is from
  another release, on stderr. They look in `.agents/skills` at the project's root and in the
  user's folder. A copy made with `--dir`, or one in a directory between the working
  directory and the project's root, is not found, and neither is a plugin, which its agent
  tool keeps. An agent tool that does not show a command's stderr to the model, or to the
  person, shows nobody the line, and a process started with its error stream closed is told
  nothing. And a copy committed with the project reaches a co-author as old as it was
  committed. The comparison is of the two version numbers and of nothing else, so it is as
  fine as the numbers are: a copy made from a checkout whose skills later change under the
  same number is not named. An install from `main` between a merge and the bump of the
  version that follows it is in the same case.
- **Two copies run at once into one folder can fail, and the next heals it.** Each stages a
  skill in a folder of its own, but both move it into the same place, and one can find the
  place taken or the old folder gone and stop with an error. Neither loses anything of the
  user's (seen by the reviewer in eight trials), and a run on its own afterwards finishes
  the copy. A process killed outright in the middle leaves its staging folder, named
  `.<skill>.<random>.partial`, and so does an old copy that holds a file which cannot be
  removed, a read-only one on Windows: the staging folder is removed without stopping at
  what will not go. Nothing cleans either up. A digest that reads
  CRLF as LF also calls two binary files the same when they differ only so; the skills hold
  text. And a folder taken as holding a skill's text is recorded as this tool's even where
  the user made it: a later release then replaces it.
- **A copy shares its folder with every other skill the user has.** The skills are copied
  under their own names, because a skill's name must be its folder's and the gates' hints
  name them ("the review-panel skill"). Where the user already has a skill of the same name
  it is left and ours is not copied, so a hint then leads to theirs. `install-skills` says so
  and exits 1; `--project` copies into the project, where nothing else is. A Codex user who
  installs the plugin and also has a copy has every skill in two places Codex reads; what
  Codex then shows was not watched.
- **Gemini CLI, Mistral Vibe and Kimi Code CLI get the skills and no hooks.** Each has a hook
  system of its own, with other event names and another way to refuse (read from their
  documentation on 2026-10-02), and none is wired here. Under those tools nothing is caught
  at the moment of the mistake, and what `check`, `build` and `submit` catch is caught later.
  Kimi's hooks could not carry it all in any case: by its documentation what a hook prints
  after a tool call or at the start of a session never reaches the model, so only the two
  guards that refuse could work there. How far each was seen: Gemini CLI 0.58.0 lists all
  fourteen skills from a project's `.agents/skills` (`gemini skills list`, which calls no
  model, and is a test where Gemini CLI is installed); that Mistral Vibe and Kimi Code CLI
  read the folder is from their documentation. No skill has been activated in a session of
  any of the three.
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
  moving the row and cell separators the reader writes before the cell's text. A table
  whose every row was deleted or moved away is the exception, since nothing of it is left
  to join into: the paragraph runs on past it into the next, as Word 16 shows it.
- **The audit and the import read every `mc:Choice` and no `mc:Fallback`, whatever the
  choice requires.** Word does the same for everything it writes, since it writes a choice
  only where it understands it. Text that sits only in a fallback, behind a choice the
  readers do not know, goes unread: Word does this for an emoji, whose choice
  (`w16se:symEx`) both readers know, and would for any other such element it adds. In the
  import that loses the co-author's insertion, and where Word writes text already in the
  source that way, `--apply` deletes it from the source. A second choice, which the format
  allows and Word does not write, would be read as well as the first.
- **A symbol with no text refuses its paragraph in the import, and reads as a space in the
  audit.** A Wingdings check box, or the smiley AutoCorrect makes of `:)`, that a co-author
  adds to a sentence costs a manual edit in the .md, and so does Symbol-font text whose font
  a style, the defaults or the theme sets: it is read, but a style's font is not taken as
  exact. The audit reads the style's font the same way and cannot refuse, so its reading of
  such text is as good as the resolution.
- **Fonts are resolved as far as the run, its styles, the defaults and the theme.** A table
  style's font, the complex-script font (`w:cs`, with `w:rtl` or `w:cs` on the run) and an
  East Asian font of Symbol drawing CJK text are not considered: such text is read as the
  characters it holds. A symbol font the reader does not know by name, in a document with no
  font table to say so, is read as the letters it is stored as. A private-use character in
  a font that is not a symbol font - an icon font's, or one pasted into the body text - is
  kept as it is, and refused in the import only when the paragraph came back holding more of
  that code than it was sent with. One deleted and another of the same code typed elsewhere
  in the paragraph count as no change, and merge as the character moved, which the build
  draws in the body font as before.
- **The import refuses a document whose styles, theme, font table or document relationships
  it cannot read safely.** Without them it cannot tell which font a run is in. Word does not
  write such parts; the audit, which cannot refuse, reads only the fonts a run names itself,
  and reads without the document's own heading styles, taking only Word's built-in ones as
  headings. A part zipfile cannot decompress - Deflate64, which some zip tools write when
  a document is zipped again, or an encrypted one - is such a part, and so is one declaring
  an encoding the XML parser cannot read. Each used to crash the reader that met it, the
  import or the audit, on the body, the comments, the styles or the font parts; a part that
  could not be decompressed crashed the import on the build's record as well.
- **A table cell styled as a heading ends a reference list.** A cell never starts one,
  since "References" there is a column header, but a heading-styled cell after the list's
  heading ends it, as it would anywhere: Word lists such a cell as a heading in its
  navigation pane. A reference list laid out as a table, with a heading-styled cell among
  its rows, is cut there, and the entries after it are reported as numbers not found.
  Letting cells run the list on would instead leave a table placed after the references,
  under no heading of its own, silently unaudited as part of them.
- **A table row is read as gone only when it is marked the way Word 16 marks one.** That
  is its properties marking it deleted, or every paragraph in it, a nested table's
  included, having its mark moved away. A text box anchored in the moved text is not
  counted, since Word marks none of its paragraphs; one anchored in text that stays, or
  that was inserted, is counted, and keeps the row. Word treats some rows marked
  otherwise, which Word 16 does not write, differently from the reader, which reads them
  as they stand, a heading-styled cell in one still ending a reference list: a row inside
  a move range with only some of its marks moved, which Word drops with its unmoved cells,
  and a row whose every paragraph mark is deleted with no mark on the row, which Word
  drops, running any text left in it on into the next row (verified 2026-09-25). A row
  with any mark left in place is otherwise read, as Word keeps it. Word 16 records neither a deleted cell nor a
  deleted column as a tracked change, so a cell marked deleted in its properties
  (`w:tcPr/w:cellDel`), which the format allows and another program may write, is read
  as present, and an empty one leaves an empty line.
- **A `References` line in code that is not fenced can start a reference list.** In
  Markdown a line in a fenced block, an HTML comment or the front matter never starts one,
  and an unmarked `# References` never does, so an R or Python comment in a fenced listing
  cannot. But a listing that is not fenced is not code as far as the reader can tell. In
  Markdown, `# References` starting a block there is a heading, and pandoc prints it as
  one. An indented block is not blanked, because `pdftotext -layout` indents real
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
  prints, and a `<!--` in an indented code block is read as a comment, though pandoc
  prints it as code. The old regex did all of this and more.

  A comment that runs out of a list item, a quotation, a definition or its term, a footnote
  or a line of a line block is now refused (`unclear-comment`, by `check`, the build and
  `audit`), and so is one that a stray backtick in one item, pairing with the one opening
  `` `<!--` `` in the next, made to the gates. Pandoc reads each such block on its own, so
  a `<!--` straight under an item's line is text continuing the item, and with its `-->`
  past a blank line pandoc printed the comment the gates had masked. The refusal reads each
  block alone and refuses a comment it does not find there
  (`comments.unclear_comment_lines`). Two readings are pandoc's own, found by the first
  review: inside a comment an item opened, a marker at or past the item's text is the
  item's, and one short of it ends the item, so a sub-list commented out on the item's lines
  is not refused; and a table or a line block ends at a line at the margin that is not one
  of its `|` lines, so a `<!--` under a table's last row is not refused. A comment on its
  own line under a blank line, and one in a paragraph at the margin, are not refused
  either.

  Elsewhere the blocks are cut short where pandoc's are not worth modelling, so some
  comments pandoc drops are refused too:
  - one across a blank line in an item's indented lines or a footnote's paragraphs, and a
    `<!--` under a blank line after a list, indented less than the item's text;
  - a sub-item commented out under a blank line in its item, or indented past its item's
    marker and short of its text, as `    - sub` under `   - item`, which pandoc reads as
    the item's because a marker four spaces in starts no item;
  - one across a quotation's paragraphs, a `>` line between them, and one across a `>`
    alone or a `|` line that pandoc reads as text continuing an item;
  - one on the line after a div's closing `:::` under a list, or after a line indented
    under a table;
  - a multi-line one straight after a listing whose code has a line starting `+ `, `- `,
    `* `, `> ` or `| `, since the blocks are read inside listings: ggplot's `+ geom_point()`;
  - one across a blank line in a `: Caption` under a table;
  - one opened on a line of a paragraph that only looks like a marker, `> 65 years` or `- 5`.

  And it does not close the gap whole. Some comments pandoc prints are still masked and not
  refused:
  - a `<!--` on a line the refusal takes for the end of a block, under an item:
    `</div> <!-- x`, `</span> <!-- x`, or `::: <!-- x`, with the `-->` past a blank line or
    in the next item;
  - one in an item whose ordered marker has ten digits or more, or on a first line behind a
    byte-order mark, which the refusal does not take for an item;
  - one on a line with a line of dashes under it, which pandoc reads as a setext title or,
    under an item's line, a table in the item: `Results <!-- x` over `-------`, or
    `- a <!-- x` over `---`, as on main.
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
  in the body, a comment stays inside the value it was opened in, and a URL ends at the
  value's end. But each of these can still hide a number pandoc prints, all on contrived
  input:
  - a fence opened in one YAML value and closed in another;
  - a `<!--` in one item of a keyword list, which runs through the next to a `-->`, or one in
    a quoted title, which a `# -->` YAML comment after it closes;
  - a code block in an abstract indented four spaces, which is not found.
  The build strips the manuscript's front matter, so these matter to `audit`, which reads
  papers another tool built, more than to G2. Reading each YAML value on its own, from
  where PyYAML places it, and un-indenting a block scalar before looking for code in it,
  would close all three. A YAML block in the middle of the body heads nothing, as in
  pandoc (`masking.metadata_blocks`), but its values are read as any text is: the build
  passes it to pandoc, which prints some of them, so masking it hid printed numbers. A
  fence opened in one can still pair with a fence in the body below it. In a
  manuscript's source, `check` and the build refuse such a block, a line of dashes with
  a line under it (#65).
- **A line of dashes wholly inside a block quote, or indented four columns in a list item,
  is not refused by `check`.** Pandoc reads YAML metadata and tables inside either; the
  refusal reads lines at the margin, or behind markup or a list marker. While every
  line of it stays inside the quotation or the item, the gates read it as quoted or listed
  text: its numbers are read, the safe side, and no heading is made from it. A `title:` in
  such a block is caught by the build, which compares pandoc's metadata with its header's,
  and not by `check`. A closing rule back at the margin, directly under the quotation or the
  item, is refused like any line of dashes with a line above it; pandoc does take the title
  from `> ---`, `> title: Evil` and `---`. With a blank line before the rule, pandoc closes
  the quotation first and reads no metadata.
- **Some shapes only the build catches.** A comment the heading scan misreads, a `<!--` that
  pandoc prints in indented code (#39 taught it inline code, `\<!--`, `<!-->` and
  `<!--->`), hides every rule up to the next `-->` from the refusal. So does a comment left open at
  the end of one file and closed in the next, since the build joins the files and pandoc
  reads across the join; a fence left open that way is refused, an opener with no closer in
  its own file. So does a `#` line straight under a line of text, `We also saw it.` over
  `# Sensitivity`, a heading to the gates and text to pandoc (#38's walk reads it as pandoc
  does). So does a block-level tag or a TeX command partway along a line of text before
  three dashes, `The dose was halved <div>---` or `Some text \include{x}---`, where pandoc
  ends the paragraph and reads YAML under the dashes; the refusal reads such a tag only at
  the start of a line (the ninth review of #65). Where the result is metadata in the text,
  a heading the gates read otherwise or a listing pandoc does not make, the build refuses;
  `check` passes it. A number such a shape hides from G2, with none of those, is caught by
  nothing.

  The comments and raw blocks `check` tracks for the fence refusal are a model too, and the
  fifth review of #71 found ten ways past it and the sixth two more, each a listing the
  gates read that pandoc prints as raw text or prose, the build refusing every one:
  - a `<pre>` or `<?php` behind text on its line, whose closer comes later;
  - a `<pre>` straight after a comment closed on the same line;
  - a `</pre>` inside a comment inside a `<pre>`;
  - a `?>` in quotes in a processing instruction;
  - an escaped `\\end{center}`, or one after a TeX comment's `%` on its line;
  - a `</pre>` inside an attribute of the `<pre>` it seems to close, `<pre title="</pre>">`;
  - code spans the tracker pairs otherwise than pandoc: backticks straddling a comment's
    close, a backslash escaping one backtick of a run, a span from the line above closing
    early, and an unpaired backtick opening a false comment that takes in a real `<pre>`.
- **Some listings pandoc makes are refused.** The same tracker opens a context pandoc does
  not, and every later listing in the file is refused, the finding on the listing's own
  lines; save one a false comment holds whole, which `check` lets be and the build finds in
  pandoc's code. The fifth and sixth reviews of #71 found:
  - a `<pre>` or `\begin{center}` opened inside one of its name and left unclosed, which
    pandoc takes for a lone tag, pairing the inner one with the closer, and a nested
    `\begin{verbatim}`;
  - a mark with no closer: an unclosed `<!-- TODO`, or a `<script>`, `<?php` or `<pre>`
    never closed, which pandoc reads as text;
  - `\begin{center}` named in a line of prose, `<pre/>`, `</pre foo>`, and a `<!--` in
    indented code;
  - a line whose backticks do not pair, `` `<!--` `` beside a stray `` ` ``, where a
    comment's mark is read.

  The hint names an open comment or raw block as a cause, and nothing is read wrongly.
- **A listing commented out with `-->` on its closing line is refused.** In ```` ``` --> ````
  or ```` ```--> ````, pandoc reads the whole listing as the comment, and the gates read no
  closer there: a closer is its fence and spaces only. So the opener is left unpaired, or
  pairs with a later fence across printed prose. Accepting it would mean ending a listing
  and a comment on one line, in the fence reader, which reads before any comment is known.
  So it stays refused, and the hint says to put the comment's `-->` on a line of its own,
  which is accepted.
- **More listings commented out whole are refused.** A tilde listing straight under the
  `<!--` line; a listing inside a commented-out list item; a backtick listing straight
  under a line of text that opens the comment, `Text <!-- aside`; and, found by the fourth
  round, one straight under comment text wrapped onto the line above it, one under a
  `<!--` straight under a paragraph or a heading, a second listing with text between it and
  the first in one comment, and one under a `<!--` indented a space. Pandoc prints nothing
  of any, and #65's build did. A listing a comment holds is let be only where
  pandoc would read it as the gates do without the comment: a tilde fence does not open
  under a line of text, and a list item's listing ends at pandoc's closer, not the gates'.
  A backtick fence does open under a line of text, but under a footnote's line, or a list
  item's with more than one, pandoc took it into the note or the item, ended it at an
  indented closer and printed the claim after it; so one is held only straight under a
  `<!--` that starts its line, with a blank line, the file's start or a listing's closer
  above it (the third round of review). A
  blank line under `<!--`, `<!--` on a line of its own after a blank line, or the listing
  moved out of the item, is accepted.
- **A fence's attribute letters are Python's Unicode, not pandoc's.** A class or a key
  starts with a letter, and pandoc 3.9 knows Unicode 15.1. Python 3.10 knows 13.0, 3.11
  14.0, 3.12 15.0 (622 letters short, CJK Extension I), 3.13 15.1, and 3.14 16.0. On an
  older Python a class starting with a letter it does not know opens a fence to pandoc
  alone, and the line is refused; on 3.14 a letter pandoc does not know opens a fence pandoc
  prints as text, which the build's comparison of listings then refuses. Nobody names a
  class in those letters by accident.
- **A fence in the front matter is read and not refused.** `masking.fenced_blocks` reads
  fences inside YAML values, and nothing refuses an unclear one there: an R Markdown chunk
  pair or a tilde fence in `abstract: |` hides the prose between from the gates. The build
  prints no front-matter value today, so nothing is printed wrongly, but a gate reading the
  abstract reads less of it than pandoc does.
- **Two misreads that cancel pass the build's comparison.** Headings are compared in order,
  not by where they stand, since pandoc's reading says nothing of where. A heading the gates
  read in one place and not in another, `# Methods` straight under a line of text early on
  and a real `# Methods` hidden by a misread comment later, lines up with pandoc's list, and
  a claim between the two passes G2 under the wrong heading. It takes two misreads, each of
  a shape above, of headings with the same title. A heading pandoc makes in a list, a
  definition or a table never lines up. The gates read none there but a setext title in a
  list item, `- Results` over `===`, which they take marker and all; it is refused as one
  pandoc reads as text or in a list.
- **Values that move a heading pass the build's comparison.** A file's headings as written
  and as built, values in, are paired by index, and refused only when their number or
  levels differ. Values whose text holds markup can move one while both stay the same: the
  ninth review emitted three strings with `label=True`, one holding a line break and a
  `# Results` line, one a `<!--` and one a `-->` around the real heading, and the claim
  between Methods and the moved heading printed under Results while `check` filed it under
  Methods. It takes an analysis emitting markup as a value; a value with a line break or a
  comment's mark is not a number, and mapping each heading through the substitutions,
  which would close this, is not done.
- **Two headings the build refuses that print as the gates read them.** An unlabelled
  `(@)` example list item before `(@good)`: pandoc numbers `(@good)` 2 in the document and
  1 in the titles set out on their own, so `## As in example (@good)` is refused. And a
  setext `===` title starting with a placeholder whose value starts with `#`, `#1 ranked
  drugs`: pandoc prints the heading, and the gates, reading the built line, do not. Both
  are refused, not passed.
- **Some lines of dashes after a TeX command are refused that open nothing.** The refusal
  takes any command for one pandoc starts a block behind, where pandoc does so only for a
  block-level command, `\newpage` or `\vspace{1em}`: behind `\foo[x]{1em}`, which it reads
  inline, the dashes are text. And a colon after a command is read as a definition's
  marker, where pandoc reads `\newpage[^1]: ---` and `\foo[x]: ---` as the command, then
  text. Each is refused though it prints as it reads; putting the command on a line of its
  own clears it. Telling the block-level commands from the rest would mean keeping pandoc's
  list of them. A definition, `\newcommand` and its kin, takes brackets after its groups
  too, so `\newcommand{\foo}{bar}[x] ---` and `\newcommand{a}[^x] ---` are refused, where
  pandoc reads the brackets as text and no YAML under them.
- **A footnote-shaped line in a `<pre>` or a TeX environment is copied to the titles.** The
  definitions the titles may refer to are taken from the text the gates do not take for
  code or a comment, and a `<pre>` or `\begin{verbatim}` is neither to them. A line there
  shaped `[^n1]:` over YAML pandoc cannot read makes the titles' run fail while the document
  reads, and the build refuses the document, where pandoc reads the block as raw markup and
  no footnote. Refused, not passed.
- **A title continuing a paragraph over `===` is read as a heading by `check`.** Pandoc
  reads `We also saw\nMethods\n=======` as one paragraph and the heading scan as a level-1
  Methods heading, so `check` puts the paragraph's numbers under Methods. The build compares
  its headings with pandoc's and refuses the document. The heading walk of #38, which knows
  what continues a paragraph, reads it as pandoc does.
- **A Methods footnote defined outside Methods is read as a finding.** A number in a note
  must pass where the definition stands as well as at each reference, so a note referenced
  from Methods and defined at the end of the paper, as authors gather them, has its alpha
  (`p < 0.05`) reported as unbound in the last section, as it always was. Judging it at the
  references alone fixed that and let five misread shapes pass in Results (review of #77);
  a number is never judged in fewer places than before. Moving the definition into Methods,
  or binding the value, clears it.
- **The end of a footnote's text is read short of pandoc's in places.** A lazy line pandoc
  keeps in a note after one that may start a block (`# Heading` straight under the
  definition, which pandoc prints as note text), or an unindented line continuing an
  indented paragraph of the note, is judged only where it sits: a `p < 0.001` there, in a
  note defined under Methods and referenced from Results, still passes as the alpha, as on
  `main`. A marker in inline code, `` `[^n]` ``, counts as a reference, which only adds a
  section a number must pass in. A line shaped like a heading that pandoc prints as text
  refuses a definition and ends a note's text only where `main` read a heading: a setext
  title does, and an empty heading's title, or a title starting `#`, `>` or `|`, does not.
- **A footnote defined in one file and referenced from another is read where it stands.**
  Notes are indexed a file at a time, and the build joins the files, so a Results sentence
  in main.md referencing `[^n]`, defined under a Methods heading in `appendix.md`, prints
  the note's `p < 0.001` under Results while G2 reads it under Methods, as the alpha, as on
  `main` (the fix-only review of #77). Indexing notes over the joined text would close it.
- **A note's text the gates misread is judged where it stands, and can fail there.** A
  number must pass where it stands as well as at each reference, which is what keeps a
  misread note from passing a Results claim; the other side is an alpha in Methods failing
  when the gates take it for the text of a note referenced from Results, which pandoc prints
  where it stands. The fix-only review of #77 found five such shapes, each contrived: an
  alpha after a note's definition in a list item, after a comment, after a line of no-break
  spaces, on a lazy `[^n]:` line under a paragraph, and in a note nested in another. Each
  is reported unbound, not passed.
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
  indented `  # References`, one directly under a line of prose, or a Word paragraph typed
  as `# References` without a heading style: pandoc or Word prints each as text, so nothing
  is cut, and a paper with no other reference heading is read as having none. Its lines are
  then taken for reference entries by their shape, as in any headingless paper, and a
  sentence with an entry's shape has its unmatched numbers listed apart, where `--strict`
  does not count them. Such a line still ends a list that a real heading started, so an
  appendix heading written directly under the last entry stops the cut early rather than
  hiding the appendix.
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
  reading emphasis as pandoc does. Other markup stays in the title, and G2 reads a title
  as Results through the marks around it, so `# **Results**` is Results; it reads Methods
  strictly, so `# **Methods**` is not Methods. In a .docx a heading style is what makes a
  heading, so a styled paragraph typed as `References {-}` starts a list, although Word
  prints the braces.
- **A heading nested in a list item is read with its marker, or not at all.** Pandoc prints
  `- Results` over an underline as a list item holding a heading titled "Results". The
  gates keep the marker in the title, so it ends the section above; "- Results" is read as
  Results, and "- Methods" never opens Methods. They do not see a heading pandoc finds
  further into an item: an indented one, one under a later item's own underline, or
  `- # Results` on the item's own line. The same goes for a definition list. The old scan
  saw none of these either.
- **List numbering is read where pandoc starts a list item, and only in Markdown.**
  `ordered-list-marker` took any line opening with "412. " for numbering, so a count a hard
  wrap put there passed G2; a list cannot interrupt a paragraph, and the rule now holds
  only where the walk in `text/blocks.py` starts an item. A .docx and a figure's text have
  no wrapped paragraphs, so the audit and G3 read them a paragraph or an element per line,
  as before: "2. The second criterion" typed in Word is numbering, and so is a Word
  paragraph that opens with a count and a full stop, which is not compared. A marker must be
  followed by a space, a tab or a line break, so a table cell, a keyword or an emitted
  string reading "412." is compared. A `#` typed at the start of a Word paragraph is
  text, since Word's headings carry a style, so its number is compared. A plain-text paper
  is read as Markdown, so one exported a paragraph per line with no blank lines between
  reads as a single paragraph, and typed numbering after its first line is reported. A
  numbered item indented four spaces or more is never taken for numbering, though one nested
  under an item with a tab is, as an editor indents a list level, and nor is one in
  the lines of a definition list (`Term`, then `:   Definition`), where pandoc does start
  lists; both are reported rather than excused. Pandoc folds the digits opening the line
  under a bare LaTeX command, `\newpage`, into the raw block, and the gates follow that at
  the start of a block. A numbered title over an underline there is still a heading: pandoc
  prints "2. Results" as ". Results", and the gates keep the number. `numbered-heading`
  takes numbering's shape only: on a `#` heading of one to six hashes, components of one or
  two digits, "2.1 Statistical analysis"; on a setext title, list numbering's shape, "2.
  Results"; then a capital or the end of the line. On a `#` heading, emphasis or a link may
  come before the capital, "2.1 *Sensitivity analyses*", and closing hashes before the end
  of the line, "## 12 ##". The walk reads the last row of a table
  written with dashes as a setext title over the rule under it, so a looser shape passed
  "12 Patients" or "3.84" in such a cell. "412 serious reports", "3.84 times higher", a
  setext title's own "2.1" and a heading of seven hashes are reported, as is a title whose
  first word is lower case or starts with a capital outside A to Z. A cell of such a table
  reading "12. Patients" still passes as numbering, as it did before, and so does a
  numbered line pandoc reads as a table's header row over a spaced rule, or as a second
  term under a definition. Inside a list item's lines pandoc folds the digits in some
  positions and not others, and there an indented "1." under `\newpage` is still taken for
  numbering.
- **Every indented line under a list is the list's for headings.** Pandoc ends a list at a
  line indented less than the item's text that starts no item, at a definition under it,
  and at a rule at the margin. The walk ends the items there, so a count opening a later
  line is not list numbering, but reads each line up to the next one at the margin as the
  list's text, as it did before it read list items. A rule shaped like a marker, `* * *`,
  and a marker in digits pandoc does not read, `１.`, do not count as that line: the walk
  read both as markers then. Read as blocks of their own, lines indented one to three
  spaces were misread (a comment, a line block, raw HTML over an indented line), and a `#`
  line under them, which pandoc prints as text, opened Methods. The cost is a heading
  pandoc prints directly under such a line: under `1. Item`, a blank line and `  ***`,
  "## 12 Patients" is a heading, and the gates read it as text, so its number is reported
  and it opens no Methods. After such a line the walk records no item until a line at the
  margin that is not a lazy line of the list, so a numbered item pandoc starts there is
  reported: a new list under `1. First` and an indented paragraph (` 2. Second`), a nested
  item under a line of the outer item of a nested list, which pandoc keeps in the list,
  and an outer item (`2. Second step`) directly under such a line.
- **A fence directly under a line of prose is code to the gates and prose to pandoc.**
  Pandoc lets only a backtick fence at the margin interrupt a paragraph. A tilde fence, or
  one indented a space or more, is printed as text, until a blank line ends the paragraph,
  after which a `# Results` still inside the "fence" is a heading. `fenced_spans` does not
  know about paragraphs and blanks the whole span, so the numbers in it go unread by G2, and
  that heading is missed. The old scan did the same.
- **A YAML block in the middle of a document is read as prose.** Pandoc takes `---` after a
  blank line, a YAML mapping or nothing but comments, and a closing `---` or `...` for
  metadata anywhere in a document, and prints none of it. The gates read it all. A number in
  one is reported, which is only noise, but a `#` line in one is taken for a heading:
  `---`, `# Methods`, `note: x`, `---` under a Results heading re-admits the `methods_only`
  rules below it. Telling one from a rule, a sentence and a rule, which pandoc prints as a
  table, needs a YAML parse. A bare `---` over `---` is read as a heading titled "---".
- **A table written with lines of dashes is read as a paragraph.** A multiline table, or a
  simple table with no header or under a `Table:` caption, is not modelled. A row reading
  `# Top`, or a title over its dashes, is taken for a heading, and one pandoc prints under
  the table is taken for text. A heading the gates miss under such a table still ends the
  section for G2 and cannot open Methods. A row they take for a heading can: `# Methods`
  between two lines of spaced dashes is a table cell to pandoc and a Methods heading to the
  gates. Word counts and the required-section check go by the headings the gates place, and
  miss the one under the table.
- **A line shaped like a heading always ends a section for G2.** A `#` line or an underlined
  title that pandoc prints as text, because it continues a paragraph, a list item or a
  quotation, or sits in a `<pre>` or a LaTeX environment, still closes the section above it
  for G2, titled as the line reads, and never opens Methods. A Methods paragraph hard-wrapped
  so that a line starts "# of reports" therefore reports the thresholds after it. The line
  prints as text in the paper as well, so it is worth rewrapping, or escaping as `\#`.
  Rows of a table the walk reads, and `{{table.x}}`, are not such lines: the rule under the
  last row is a rule. Four kinds of heading pandoc does print are read the same way: a `#`
  heading after a tag or a comment on its line, a setext title after a tag, at the start of
  its line or after a comment, a setext title starting `>` or `|` or made only of dashes,
  and a heading of seven hashes or more. The scan before the walk never read any of them,
  and where the walk wrongly starts a block, under a stray `</script>` say, or ends a tag at
  a `>` pandoc reads inside a quote, one would open Methods; so a Methods section headed
  that way reports its thresholds. Such a line that says Results holds the Results in place
  like a printed heading. A lone `##` over a line of text, an empty heading and a paragraph
  to pandoc, ends the section there, titled with that line, whether the walk places the
  `##` or not; a `#` line under it, which the scan before the walk took for its title, never
  opens Methods. A setext title that is an ATX line at the margin, `## Outcomes` over `===`
  or `# X` over `-`, is a heading at the underline's level titled "## Outcomes" to pandoc
  and the walk, and a heading "Outcomes" at its hash count to the scan before it, which took
  a no-break space after the hashes too. The printed chain takes the hash count, and so does
  the other chain where the walk marks the line as text; for G2 a section is Methods only if
  both readings say so. The audit's reference list starts
  only at a heading G2 would call printed, so none of these starts one.
- **A pipe table's rows are found more simply than pandoc finds them.** The walk takes a
  line under a table for a row when it holds a pipe outside code, math and a backslash
  escape, and reads each of those naively: two dollars are math, a backslash escapes the
  pipe after it, and two backticks are code. Pandoc does not: `$ | $` is not math, `\\|` is
  an escaped backslash and a cell edge, an escaped backtick opens no code, and a code span
  closes only on a run of as many backticks as opened it. The walk ends the table above such a row, and reads the row as
  whatever it is shaped like, a title over the rule under it say. The scan before the walk
  read that heading too.
- **A section is Results only by its title.** `## **Results**`, `- Results` and
  `# Results` over a rule are read as Results, but a combined title such as "Results and
  discussion" is not, so a "Sensitivity analyses" under it keeps the Methods rules. The
  old scan did the same. Reading every title that starts with "Results" as Results would
  also report the thresholds under a Methods subsection called "Summary statistics".
- **A heading directly under a captioned `{{table.x}}` is printed inside the caption.** The
  build writes the caption as a paragraph after the table, and a heading cannot interrupt a
  paragraph, so the document loses the heading while G2 reads the one the source means. With
  no caption the table ends at its last row and the two agree. A blank line avoids it, as
  the example leaves one everywhere. A `{{figure.x}}` line is prose to both: the
  build writes an image there, and a heading under it is printed as text.
- **Raw HTML and LaTeX beside a heading are read from lists, not from pandoc's parser.** A
  line of nothing but LaTeX commands is a block unless one of them is on a list of inline
  commands. A tag is block-level, "either" (a block at the margin, inline in a paragraph),
  verbatim (`pre`, `script`, `style`, `textarea`, holding everything to their closing tag)
  or inline, by list. A paragraph ends at a line starting with a block-level tag, and after
  one whose last tag is block-level or closes an HTML block counted open around it. Every
  entry was checked against pandoc 3.9, and a name on no list is read as pandoc reads most
  unknown ones: a LaTeX command as a block, a tag as inline. A block quote's lazy lines stop
  at the closing tag of an HTML block counted open around them. Only a tag that starts a
  block is counted open, so one opened in the middle of a line, inside a paragraph, or
  inside a table or a LaTeX environment, is not; a closing tag anywhere on a line closes it,
  one quoted in inline code included, which can end the block early. A stray `</script>`
  inside a paragraph ends the paragraph, where pandoc reads it inline. A comment at the
  margin is a block and the rest of its line starts the next one; indented one to three
  spaces it is inline, except directly under an "either" tag alone on its line, which takes
  it into its raw block, and inside a list, where the gates still read it as a block. What
  follows a comment on its line is text, never an underline or a rule. Pandoc also drops
  the indentation of the line after a raw block, `<hr>` or `\newpage` alone on a line, and
  prints it as a paragraph; the gates read it as code, so a `## Methods` directly under it,
  text to pandoc, is a heading to them and opens Methods, as it did for the scan before the
  walk. Pandoc reads a setext title that is only an HTML comment as an empty heading,
  where the gates see none. A heading's title keeps its raw HTML and LaTeX, which pandoc's
  printed title does not show, so `## Methods <span>` is not read as Methods. It is read
  as Results through them: `# <del>Results</del>` and `# Results \label{sec:results}` end
  the Methods as the printed "Results" does. In a file
  with CRLF line endings the gates now see setext headings, which the scan before the walk
  did not, and with them the list-heading gaps above.
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
- **ARRIVE's page is cut where poppler's `pdftotext` lays it out.** The one from Xpdf, which
  Git for Windows puts on PATH, sets the two columns at other positions, the recipe's
  `column_split` does not fit, and the transcription stops at `no items found on pages
  (2,)` without a word about which `pdftotext` it wants.
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
  is the paragraph's position in the file, and applying a reorder moves text between slots,
  so a `where:` anchor recorded before the reorder afterwards names different text. G13 no
  longer depends on it: it asks whether the text the reviewer read is still there, which is
  the question it had, and a revision that edits the paragraph is exactly what should stop
  it matching. What remains positional is the `where` a person reads in the round file, and
  the identifiers of a document sent out before the source changed. Persisting the
  identifier in the source rather than deriving it would fix both, and it is not done.
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
- **A rule's phrase crosses one line break between words, not two.** "Table" and its 2,
  "STROBE" and 14, "p" and `< 0.05` may be split by a hard wrap, and still match. With a
  blank line between them they are two paragraphs, and the number opening the second is
  reported: `\s*` used to cross any number of line breaks, and a count opening a paragraph
  after one ending "the next section" passed as a cross-reference. The rewrite that made
  every rule linear is what set the limit. The same limit lets a label opening a paragraph
  match as it does on its own: after a paragraph ending "one year", "12-month outcomes" is a
  time label, where the match that crossed the blank line used to take its digits and leave
  "12-month" reported, and in the audit "(2019, n = 412)" after "et al." is now read as the
  whole parenthetical it is anywhere else. The other way, a count that such a match left to
  the rule's next match can be reported now. In a rendered author-year citation, a name is
  at most 61 letters; a longer one is read as no name, and its year is compared.
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
- **A document from before paragraphs were recorded is judged by the front-matter rules
  only.** Whether it still names the right paragraphs is worked out from the rules of 0.2.12
  and of 0.2.13 until 0.2.47, and from which blocks 0.2.45 and 0.2.49 changed the tagging of.
  Any other change to how paragraphs are numbered cannot be detected for such a document.
  One is known: builds from before front matter was stripped at all (0.1.0, before #7)
  counted the header as a block, so every identifier is two higher than now, and such a
  document, returned against an unchanged source, would be merged into the wrong
  paragraphs. Rebuild any document that old rather than import it.
- **Such a document can also be refused needlessly.** It is refused whenever anything it
  was built from has changed since, `--force` or not, because its numbering can only be
  checked against the text it was built from; a re-run analysis alone is enough. And it is
  refused when a file it carries has a header some past release read differently from this
  one, whichever release built it: a blank line after the opening `---`, a `...` closer, a
  trailing space on the opening `---`, a byte-order mark or a blank line before it, or a
  header pandoc prints rather than keeps, a list or a sentence. `init` writes none of
  these. Returned untouched, one from before 0.2.49 also exits 1 over each paragraph that is
  only a value, named as not in it, which it never carried. Either way, the refusal's own
  advice is the way through: rebuild and resend.
- **A paragraph the source changed since the build takes no co-author edit, even under
  `--force`.** Its identifier no longer names the text they edited, so the edit is named and
  left, to be carried over by hand, even when it would have merged cleanly. So is an edit to
  a paragraph that reads word for word like another in its file once the block before it
  changed, and to the paragraph before one that is left out of the comparison and did not
  come back, which may be a join.
- **A paragraph whose identifier shifted is followed only where nothing beside it
  changed.** Below a paragraph the source added or removed since the build, identifiers
  moved by a block and name their neighbours; a paragraph is followed to where it stands now
  only as `_followed` allows, and the rest are named as not compared, their edits carried
  over by hand:
  - the paragraph directly beside what the author added, removed, moved or reworded, and
    any beside a heading, caption, table or comment changed since, since its record or the
    text of the paragraph before or after it differs;
  - a paragraph whose text, the blocks around it and the text of the paragraphs either side
    of it are found more than once in its file, then or now, such as "None." under the same
    heading between two others that read "None.";
  - a paragraph out of order with the others compared, the author having moved it or a run
    around it: of two runs swapped, the middle of only one is followed;
  - a paragraph moved into another file, and every one in a document built before the
    record held the blocks around each paragraph.

  A followed paragraph's rewording is also refused beside a heading or caption missing from
  the returned document, and when the paragraph after it as sent did not come back, as is
  that of the paragraph before a followed one that did not, though each may be the
  co-author's own deletion. A heading the author moved in the `.md` past a
  followed paragraph, or past a run around it, leaves the paragraph where Word has it on the
  other side of the heading: reported as moved into another section, not applied, and marked
  as changed in the `.md` above it. A run of three paragraphs or more deleted and written
  again word for word elsewhere in the same file, in the same order, is taken for the one
  sent, as trust in place assumes the same of a paragraph that reads as it did.
- **A join retyped from a paragraph left out of the comparison into the next reads as a
  deletion.** With the first paragraph not compared and the second's bookmark lost, the
  second is reported deleted in Word, and the first not compared. Nothing is written, but
  deleting the second from the `.md` as told, without carrying the first's Word text over
  by hand, loses the second's words. Main reports the join, having the first paragraph's
  text to weigh it with.
- **A document built before the record held the blocks around each paragraph is read as
  it was.** Its record hashes only each paragraph's text and the block before it. So a
  heading beside a paragraph removed from the `.md` since the build goes unseen, and a
  heading the co-author ran into the paragraph merges, as before. That covers a heading in
  its own block above or below the paragraph that keeps its place, one written straight
  above it, one past a comment, a caption, and the heading opening the next file. A renamed
  one is still caught when the document is imported with `--force`, as a heading missing
  from the returned document.
- **An edit beside a changed block is refused in a forced import.** A rewording is named
  and left to carry over by hand, though most such edits would have merged cleanly, in two
  cases:
  - the run of blocks without an identifier around the paragraph, up to the paragraphs on
    either side, changed in the `.md` since the build. That includes a paragraph added or
    removed at the far end of the run, which joins it to the next run or splits it, while
    the block beside the paragraph stays as it was;
  - in a document built from other inputs, a block without an identifier beside it, other
    than a table, was deleted by the co-author in Word or prints otherwise now: a heading,
    a caption, a list item, a quotation, an entry of the reference list.
- **A farther heading run in after the nearer one was deleted in Word is merged.** `import`
  looks only at the block directly beside a paragraph as the source has it. A co-author who
  deletes `### Design` and runs `## Methods`, above it, into the paragraph writes
  "MethodsPapa..." even in an import of an unchanged document.
- **Two paragraphs that read the same after blocks that read the same are told apart by
  position alone.** The record hashes each paragraph's text and the block before it, so
  "None." under a "# Funding" heading repeated in two places, with a copy of both added
  above them since the build, would pass for the paragraph the co-author edited, and the
  edit would land in the copy.
- **A paragraph moved in Word past one left out of the comparison may not be reported as
  moved.** Moves are worked out among the paragraphs compared, and passing one that is not
  changes nothing in their order. The import names the paragraphs left out and exits 1, and
  says this of them; the move is not applied. A move among the paragraphs compared that
  passed one left out is named as not applied, with every other move in its section; it
  used to be applied, and the moved paragraph landed on the other side of the one it
  passed.
- **Without its record of what it printed, a document is read by the older rules**, as one
  built before the record is: the entries below on the five-word rule and on an identifier
  Word left behind describe them. The record is a file beside the
  build (`build/records/`, see "The build records what each paragraph printed"): on another
  machine, or once `build/` is cleaned, it is not there. The import says so in one line and
  refuses more; nothing more is written. Committing `build/records/` or copying it with the
  project would carry it, at the price of keeping each build's text in the repository.
- **With the record, five things are still refused that are not wrong.** A paragraph
  deleted in Word whose identifier went onto the block under it, edited so that it reads
  like the paragraph too, cannot be told from the paragraph reworded with that block gone,
  and is refused either way: a sentence above the caption that repeats it. A paragraph
  rewritten past most of its words in the same round as a block of its own kind directly
  above or under it was deleted (the text beside a displayed equation, a line block, a
  div with no style) is refused, which main merges: the document is byte for byte the one
  where the paragraph was deleted and that block typed over, so one of the two has to be
  refused. Reworded less far, it merges. A paragraph whose text was deleted, whose emptied
  line was joined up, and after whose identifier something was then typed (the end of the
  heading above retyped, say) is refused and not reported deleted, as main reports it under
  a heading: what its identifier holds was typed after the join or is what is left of the
  paragraph, and the document does not say which. Nothing is written either way. The
  paragraph after such a joined-up line, reworded in the same round as the block above
  was edited, is refused as beside new text: that block has no identifier, it is edited,
  and it now stands directly above the paragraph, as an edited heading would. `main`
  merged the rewording only where it took the block for the deleted paragraph and wrote
  it over that one (a div with no style; under a quotation it refuses too). And the
  refusals that rest on hashes are not lifted: a rewording beside a heading or caption the
  `.md` changed since the build (`beside_changed`), in a stale document beside one that is
  missing (`_printed_otherwise`), or just before a paragraph left out of the comparison
  that did not come back (`_beside_lost`). The record could settle each; none is read
  from it yet.
- **Where an identifier's bookmark sits is read for a block carrying one identifier the
  record holds.** A block carrying several, or one the record does not hold, is judged by
  its kind and its words as a document without the record is (`_off_headings`). Several
  identifiers on a block are a join, reported or refused, and never merged as a rewording.
  An identifier Word's tracked changes moved has no known place, and is read as at the
  start of its block, which is where those changes put it: on the paragraph it names.
  A table, figure or equation counts as gone where the returned document holds
  none with the same content, so one edited in place counts as gone too: the text beyond
  it is then weighed with the text under the paragraph, which can refuse a rewording and
  cannot merge one. And a block of the paragraph's own kind (a line block, the text beside
  an equation) cut from elsewhere and pasted onto the line the paragraph's text was deleted
  from is read as the paragraph reworded, as any text typed or pasted there is and as on
  `main`: its text is written to the paragraph's slot, and its old place is reported as a
  block that vanished, for the author to delete.
- **The record is read as this release reads a document.** It holds each block's text as
  `docxtext.blocks` read it at the build. A release that reads a document otherwise - a
  symbol, a space - would find a paragraph's recorded text different from the text it
  reads back, and count that paragraph gone: a refusal, not a write.
- **A rewording that gained five words in a row, or a number, is refused whenever a
  paragraph that did not come back said something not known.** A paragraph the `.md`
  changed or dropped since the build, deleted in Word too, or one that is only values or
  citations in a document built from other inputs, leaves nothing to look for in the words
  another paragraph gained. Every rewording in the document that gained a run of five words
  or more, or a word with a digit in it, is refused and named, though most would have
  merged cleanly: deleting in Word a paragraph the author also changed holds such edits
  back in a forced import. One that gained less, as a word added, a word fixed or a clause
  cut does, merges. So does a paragraph of four words or fewer, with no digit, pasted into
  another, as `_swallowed` lets one through: its words go into the source twice.
- **An identifier Word left behind counts as the paragraph gone only where the text it holds
  says so.** This is the reading of a document without its record of what it printed; with
  the record, what the paragraph said is known, and the gaps of this entry are closed
  but for what the entry above names. It counts as gone where it holds nothing - in front
  of another's, on an empty
  line, at the end of a paragraph that line was joined onto - where its paragraph's text is
  known and is not in what it holds, and where it holds text that reads exactly as another
  paragraph or a heading. Where its paragraph's text is not known, holding text that reads as
  nothing sent - a sentence typed where the cut one stood, say - it counts as the paragraph,
  reworded, and a paste of its old text elsewhere is not looked for. Text typed after an
  identifier is that identifier's, wherever the identifier went: with the emptied line
  joined onto the end of the paragraph before it, by Backspace, a sentence typed there next
  is held by the cut paragraph's identifier, and counts as that paragraph the same way. Nor
  is a paste looked for where the text the identifier holds is a block the build gave no
  identifier, changed in the `.md` since the build and of the kind the identifier's own
  paragraph was built as: body text beside body text, such as a paragraph with a code fence
  directly under it, or the term of a tight definition list after a loose one deleted whole.
  Blocks of every other kind are known by their kind (`merge._off_headings`); what one of
  the same kind printed as sent is not known. The record keeps a hash of each
  source block, not what it printed, so the text read as "something else the document was
  sent with" is the fresh build's; asking the record whether the blocks beside each
  paragraph changed since would refuse every rewording that gained five words whenever the
  author had changed a paragraph and the heading beside it. Recording what each block
  printed would close all three. An untracked deletion in Word of a paragraph the author also
  changed holds back a rewording elsewhere that gained five words in a row or a number, as a
  tracked one did, and so does a block holding two identifiers where the place of either
  bookmark is not known and one's paragraph is not. And a paragraph compared whose identifier
  came back on other text is refused itself (`_not_its_own`) but not looked for in the words
  another paragraph gained, as on `main`.
- **The five-word rule is the rule for a document without its record.** The hashes of #56
  and #93 say whether a paragraph's source changed, not what it said, so what a paragraph
  deleted or cut in Word said is not known when the `.md` changed it since. The build now
  records what each paragraph printed, and for a document with that record the question
  is exact; the narrowed refusal stays for one built before it or imported away from it.
- **A copy of a re-run value, or a partial copy of under five words, merges.** A value
  paragraph copied rather than cut in Word, or a stretch of under five words copied from a
  paragraph ("Of 4000 reports screened"), in a document whose analysis was re-run since:
  the copy stays where it was, so nothing vanished, and `_swallowed` looks for a copy of
  five words or more. "...dates. 4000" merges, as on `main`, and `check` reports the typed
  number as unbound.
- **A sentence cut from a paragraph the `.md` changed since, and pasted into another,
  merges.** The paragraph it went into gained it; the paragraph it left is not compared, so
  what it lost is not seen. The sentence is in the source twice, as on `main`, and with no
  number in it `check` cannot see it. This is the sibling of the tracked case below, where
  the paragraph the sentence left is refused because a binding went with it.
- **A paragraph cut from the supplement and pasted into the main text merges.** Each
  document is imported on its own and its record covers only itself, so the main text's
  import sees new words in a paragraph and the supplement's sees a deletion, which it
  reports and does not apply. As on `main`.
- **G13 takes a surviving copy for the paragraph the reviewer read.** The commented
  paragraph counts as unrevised while the manuscript holds its exact text anywhere, so if a
  paper repeats a paragraph word for word and the author revises one copy, the other still
  reports it unchanged. That is a false alarm, the safe direction.
- **A tracked change is accepted, not shown.** The import reads the document as if every
  revision had been accepted: inserted text counts, deleted and moved-away text does not, a
  paragraph deleted as a tracked change is reported deleted, and a deleted paragraph mark
  is a join. Rejecting a co-author's change means rejecting it in Word before sending it
  back. A tracked move of a paragraph is read as the move it is; see the next entry for
  where that stops. A table, a figure or an equation is read the same way: a tracked
  deletion of one is a deletion, and a tracked move puts it where it was moved to. A
  picture or an equation inside `w:del` or `w:moveFrom` used to be read as if it were still
  there, and so did a table's deleted rows, so each came back as "nothing came back".
- **A move is applied only when Word recorded it.** Word does not carry a paragraph's
  identifier when it cuts it (see "A move, the way Word makes one"). What is left:
  - *A move made with Track Changes off, in a document built before this change (which asked
    Word not to record moves, and which `import` names), or with move tracking turned off in
    Word, is refused.* It is reported as moved in Word when its words came back elsewhere -
    most of them in order,
    a judgement that only chooses the words of the refusal - and otherwise as deleted, with
    the advice to move it rather than retype it if it was moved. The author moves it in the
    .md. With Track Changes off, the paragraph it was pasted in front of is refused too.
  - *Tracked moves are paired only when they took whole paragraphs*, as many arriving as
    leaving. A sentence moved out of one paragraph into another changes both paragraphs'
    text, and is read that way. The paragraph it left is refused if a binding went with it;
    the paragraph it arrived in merges it as typed text, numbers included, so the sentence is
    in the source twice until the author deletes one, and `check` reports the typed numbers
    as unbound. That is how any number typed in Word arrives, on `main` too.
  - *A section that gained text keeps its order.* A recorded move in a section where a
    paragraph was also split, a new one typed, or a heading or caption beside it edited, is
    reported with the new text in that section and not applied. The search for the section
    goes past a paragraph moved in, and past headings: new text beside a paragraph moved to
    the edge of its own section, or typed directly against a heading, reaches across it, and
    a clear move in the section on the other side is held too. Nothing is written. Stopping
    at a heading that read as sent was tried and taken out: a quotation cut and pasted beside
    the paragraph moved in, without Track Changes, read as sent too, hid a split's section,
    and the move between its halves was written.
  - *A rewording that gained most of a vanished paragraph's words is refused.* Most of its
    words, in order, is a judgement, and it only refuses: a paragraph deleted in one place
    and paraphrased into another, both in one round, has its rewording refused.
  - *A paragraph moved beside a reworded one refuses the rewording*, as new text beside it
    would: it cannot be told from the second half of a split.
  - *A paragraph typed in front of one that is then deleted*, with Track Changes on,
    reports the deletion and refuses a rewording of the paragraph after it, beside the new
    text. `main` merged the new text as a rewording of the deleted paragraph.
  - *With Track Changes on, a paragraph typed at the start of another is a new paragraph like
    any other*: its neighbour keeps its identifier, and the new text is only counted among
    what was not compared. It used to be refused as a split of the neighbour, which at least
    named it. With Track Changes off it still is.
  - *A comment's anchor is read from the markup only.* After a paste made without Track
    Changes at the start of a paragraph, a comment on the pasted text is attached to the
    paragraph it landed in front of.
  - *A heading is what its style says it is.* An identifier left on a heading, a caption or
    a reference entry - the paragraph before it deleted without Track Changes - names a
    paragraph that is gone, whatever the heading now says. A heading made by hand, bold and
    larger with no heading style or outline level, is not a heading to Word's navigation
    pane either, and not to `import`: retitled in the same round, it reads as the deleted
    paragraph's new wording, as every heading did on `main`. So does a heading, a caption or
    a reference entry whose new text and the paragraph deleted before it share most of
    their words, in order, which is read as that paragraph restyled: a short caption edited
    into mostly a deleted lead-in's words merges into the lead-in's slot, as on `main`, and
    the caption in the source stays as it was.
  - *A heading joined into a short paragraph under it and retitled in the same round*, in a
    document without its record of what it printed (with the record the paragraph is
    refused and nothing is written: its identifier is behind the heading's text), is no
    longer known as a join once the heading's old title is gone from the block. When the new
    title and the paragraph still share most of their words ("Ethics approval" with "Not
    applicable."), the block merges into the paragraph's slot, title and all, and the
    heading stays in the source, as on `main`; otherwise the paragraph is reported deleted,
    and Word's joined text listed as a changed heading ("Conflicts of interestNone
    declared."). Read together, those two say to delete the paragraph and retype Word's copy
    into the heading, and neither is meant: the paragraph is there. Undo the join in Word, or
    make the retitle in the .md. A copy of the heading's old title standing elsewhere in the
    document - typed as a heading of its own, say - hides the join in the same way, since
    the join is known by that title going missing, and gives the same report.
  - *A section deleted whole, with the heading after it retitled around the deleted title*
    ("Funding and competing interests", once the Funding heading and its paragraph are gone)
    is refused as a join with the deleted heading: its title gone from the document and
    turned up beside the deleted paragraph's identifier reads as one. Nothing is written,
    and the advice to undo a join points at one that was not made. Delete the section and
    retitle the heading in the .md.
  - *A heading run into a paragraph that opens with the heading's own words* ("Statistical
    analysis" over "Statistical analysis used...", joined and edited into "Statistical
    analysis: we used...") merges, heading text and all, and the heading stays in the
    source, as on `main`. A join is known by the heading's title appearing once more than it
    did, and here it appears once before and once after. Check such a paragraph in the .md
    after an import. This too is of a document without its record: with it, the paragraph's
    identifier is behind the heading's text, and the paragraph is refused.
  - *A heading carrying a slid identifier, then joined into its paragraph* - the paragraph
    before the heading deleted without Track Changes, then Delete pressed at the end of the
    heading - comes back as one block with both identifiers, and is reported as those two
    paragraphs joined into one. The deletion is not reported, and the join named is not the
    one made. Nothing is written.
  - *A paragraph sent with a caption's style* - a note in a custom-style div - keeps its
    identifier on a caption of that same style. Deleted without Track Changes just above a
    table whose caption was edited, it has the caption's new text written over it, as on
    `main`. Nothing in the toolkit writes such a div.
  - *A paragraph restyled as a heading, a list item or a quotation, or given the style of
    any other block the build leaves without an identifier, and reworded past most of its
    words* is reported deleted, and the restyled block as new text, with the document's
    record of what it printed as without it: the record cannot tell it from a new block of
    that kind typed where a deleted paragraph's identifier slid, which is the same bytes,
    and merged, that block was written over the deleted paragraph. Make the rewording in
    the .md. One restyled that keeps
    most of its words merges its rewording, and the style change is dropped without a word,
    as on `main`. So does one given a style the build uses nowhere, however much of it was
    reworded.
  - *A subheading typed above a paragraph without Track Changes* takes that paragraph's
    identifier, as any text typed at its start does, and the paragraph is reported as moved
    in Word, though it never moved. Nothing is written. Only an empty line is given its
    identifier back.
  - *The live build's reference list before Zotero refreshes it* is one placeholder paragraph
    with no style, so it is not recognised as a reference entry. The last paragraph deleted
    without Track Changes leaves its identifier on the placeholder, and its text is written
    over that paragraph, on `main` too. After a refresh the entries carry the Bibliography
    style and are recognised.
- **A join into a table is neither applied nor reported.** A paragraph whose mark was
  deleted just before a table runs on in Word into the table's first cell. Import folds a
  paragraph into the next only when no table stands between them, so it reads the paragraph
  as it was, unchanged, and the co-author's join is lost without a word. Refusing such a
  paragraph as a join would be the way to report it. Past a table deleted whole, whose rows
  import does not read, the two paragraphs are adjacent and the join is refused as any
  other.
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
  indented four spaces; and one with a `<!--` that never closes. A rewording of any of them
  is refused, and a swap with it reported rather than applied. A comment or a `\newpage`
  still ends a section though Word shows nothing there, so a swap of the two paragraphs
  around one is reported rather than applied. A co-author who drags a held paragraph past
  the one paragraph beside it sees that paragraph reported as moved; dragged past two or
  more, or past a heading, the held paragraph itself is reported. A comment opened in a
  paragraph is found first by the tagging rules, which give no identifier to a paragraph
  holding a `<!--` that closes past it. Behind them, `_bare` reads the source with code
  spans and closed comments set aside, and a backtick in a link's address, an autolink,
  inline maths or an HTML attribute can still be taken for one that opens a code span; a
  comment opened after it and closed past a blank line is then not seen by that reading.
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
  identifier at all. An equation directly after a tagged paragraph is not taken for part of
  it, since `$$` anywhere in a paragraph keeps the identifier off. One that pandoc splits
  for another reason and that ends its section is not recognised: a rewording of its first
  part would replace the rest, and a move of its first part would carry the rest along.
  Bindings are substituted after the identifiers are given, so G2 refuses a value whose
  display would split its paragraph: display maths, a LaTeX environment, an HTML block tag
  or a line break. `build --skip-checks` still builds one, and `import` then handles its
  paragraph as it did before the refusal: a rewording of the first part is refused, but a
  swap of that part with the paragraph above moves the whole sentence in the .md. Other raw
  markup in a value, such as a raw OpenXML span, is not looked at.
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
    marked. A link written straight above a paragraph or a heading is passed over, and the
    paragraph after it carries the identifier (see the next entry). Anything else - a link
    wrapped over two lines, with attributes or a title on the
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
    to both, and prints nothing. A marked line cut down to that shape in Word, such as
    `[Note]: @smith2020 says X.` to its label and citation, is refused by `import`: the next
    build would give it no identifier.
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
  - *Only a note left alone, or a label made a term, is read by itself.* Pandoc reads a
    note's text apart from the body. Directly under a label, a definition list's `:` or `~` -
    with text, a space or a tab, or alone, indented up to three spaces - makes a term and its
    definition instead, and pandoc reads each of those by itself too, so `_blocks` follows no
    raw content out of that block either (`_term_under_a_note`). Followed, a `<!--` in the
    label hid the paragraphs after it up to the next `-->`, while pandoc printed them. Only
    a block of those two lines is taken so. With a line after them, pandoc can end the
    definition inside the block - at a code fence, a list's first item, or the close of a
    div or of any tag it takes for a block around it - and what follows is at the top level.
    Taken for a term's by itself, a comment opened there was not followed and the paragraphs
    inside it were marked; two review rounds each found another such line a list had
    missed, so a longer block is followed as on `main`. What is still followed, as on
    `main`, and leaves paragraphs pandoc prints unmarked: such a longer block, a term that
    is no note's label (`Capped <!-- check` over `: as agreed`), a label with nothing after
    `]:`, a definition after a blank line, a label on the block's second line or later, and
    a definition's indented continuation. A note that runs on into the block below, or is
    marked for an underline or a table's rule, is still read for raw content as a paragraph
    is: a `<!--`, `<pre>` or `\begin{...}` in its text leaves the paragraphs after it
    unmarked, and pandoc prints them. The other way round, a note left alone takes a `:::`
    in, which ends it inside a fenced div, and a comment opened after that line is then not
    followed: `::: box` over `[^cap]: Capped`, `:::` and a `<!--` has the paragraphs after
    it, up to the one holding the `-->`, marked inside the comment, on `main` too. Following
    from the closing line on would fix it; following the whole note again would hide what
    #54's eleventh round found hidden. And a code fence wrapped onto a note's second line,
    left alone or not, is still paired with the next fence below, so what lies between goes
    unmarked, or a marker lands inside a real code block. Both are so on `main`.
  - *A note marked only for what is below it would become a definition if moved.* A note
    over a blank line and then a line indented four columns would take that line in, so it
    is marked, and prints as text. Moved in Word to a place with a plain paragraph below
    it, it would be a definition to the next build and print nothing; `import` applied such
    a move and exited 0. It now refuses it, and no move in that section is applied (next
    entry). Typed into a definition's shape in Word, a paragraph was never at risk: the
    merge escapes the bracket, `\[x]: …`, and it prints.
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
    across a definition that would carry a note marked for what is below it to where it
    becomes a definition is refused (next entry).
- **`import` refuses a write the next build would not find again, by `tag`'s reading.**
  Before anything is written, each file is worked out as `apply_plan` would write it and
  read through `marked_blocks`, the reading `tag` and `tagged_paragraphs` share. A
  paragraph written must be a marked block at the offset the splice put it, with the text
  written; one not written must keep its mark and its text. What fails is withdrawn one
  kind of cause at a time, and everything checked again after each. First a reworded
  paragraph that fails has its rewording refused, since that may be what does it. Then one
  that fails where the moves put it holds back every move in its section, and each move the
  co-author made is reported with the paragraph it would have left without an identifier.
  Holding back its own move alone pushed the paragraphs around it into other slots, so a
  paragraph nobody moved was refused, and the file came out in an order neither the source
  nor Word had; and acting on every failing paragraph at once held back moves that a
  rewording's `-->` had spoilt, not the moves themselves. Rewordings in a held section still
  land, in place, and are checked there too: back in place, a `-->` typed into one closed a
  `<!--` above it that it had not closed where it was moved, and it was merged. What that
  leaves:
  - *It is only as right as `tag`.* Where `tag` marks a block pandoc reads otherwise, the
    check takes `tag`'s word for it; the gaps in the entries above are its gaps too.
  - *A move is held back by section.* A co-author's other moves in the same section are not
    applied either, though nothing was wrong with them; they are named.
  - *A paragraph that loses its identifier to a write beside it holds back its file's
    rewordings.* `_blocks` reads across blocks - a comment or a fence opened in one runs on
    into the next - so one write can cost another paragraph its identifier, and which write
    did it cannot be told. The rewordings in that file are refused, and if that is not it,
    the moves are held after.
  - *A paragraph that never reached the document is not checked.* One inside an HTML
    comment has an identifier in the source and none in Word, and nothing writes it.
- **A paragraph under a heading or a link's definition carries the identifier.** Pandoc
  needs no blank line after a heading, nor after a link's definition, so `# Methods` with
  its paragraph on the next line is a heading and a paragraph. Every block starting with
  `#` went unmarked, and a co-author's edit to that paragraph was dropped while `import`
  said nothing came back; and a paragraph straight under a definition was marked with it,
  which printed the definition. Now the headings and definitions a block opens with - ATX
  or setext headings, and links in the strict one-line shape, under a line pandoc takes for
  blank - are passed over (`_lead_end`), and what follows them is judged as any block is:
  marked, at its own offset, when `_untagged` finds it one paragraph. What that leaves:
  - *Anything else under a heading stays unmarked with it.* A list, code, a table, or a
    paragraph with a fence or block-level HTML after it in the same block goes unmarked, as
    the whole block always did, and an edit to it is not compared. A blank line after the
    heading avoids it.
  - *Under a heading, a line that may open a definition stays unmarked.* A line opening
    `[label]:` in a shape the strict rule does not take - its title on the next line,
    `{attributes}`, words for an address - is a definition to pandoc, and a marker in front
    of it would print it and break every link to it. So it is left as the whole block
    always was, and prose that opens with `[label]:` under a heading is not compared.
  - *Under a link's definition, what is not one paragraph goes unmarked with it*, as it
    would on its own: a list, code, a table. The definition works. A definition the strict
    rule does not take, under a strict one, is the paragraph there, and is marked, and
    prints as on #54 - unless a heading was passed over too, when it is left alone as under
    a heading.
  - *Only a heading of plain text is passed over.* Markup opened in a heading's line can
    close on the next: pandoc then reads that line into an ATX heading, or a setext title
    and all under it as one paragraph, and a marker between printed inside it. Review found
    one form after another - a code span, a comment, a citation's locator (`[p. 33]` under
    `@key`, which an edit in Word then wrote into the source cut off from its citation), a
    citation group, maths, a link's destination, a tag's attributes, a backslash inside
    code. A TeX environment opened in the line and closed later does worse: pandoc reads
    no heading at all, only the line up to it as text and the environment as a raw block.
    So a heading is passed over only when its lines
    hold none of `` ` @ $ [ ] < > \ * _ ~ ^ { } & ``, apart from a closed attribute block
    ending the line (`{#sec-methods}`, which cross-references need). The emphasis marks
    among them, `*`, `_`, `~` and `^`, run on to no later line: pandoc 3.9 closes none of
    them past a heading, ATX or setext. They stay out all the same, because the allowlist
    is what ended review's search, and an exception to it would start one again. Any other
    heading stays unmarked with its paragraph, as on `main`, and that paragraph is not
    compared: `# The `lm` function`, `# Costs ($US)`, `# Contact: a@b.org`, a `<div>` line
    over an underline.
  - *A reworded paragraph can take the link above it along.* One that comes back from Word
    opening with `(`, `"` or `'` could be the title of a link's definition written straight
    above it, so the next build marks the whole block, as #54 does, and the definition
    prints as text.
  - *Setext headings are not compared, as before.* On `main` since #25 a block holding an
    underline is left unmarked whole, so the paragraph under a setext heading had no
    identifier either; it has one now, and the heading still none. A revision round opened
    on #54 and before this change, with a point anchored to a paragraph under a link's
    definition, reads that paragraph as revised: its identifier covered the definition too.
  - *`#` opens no heading unless pandoc says so.* `#Methods` and `#1 priority` are
    paragraphs to pandoc, and are marked like any other. Indented one to three spaces,
    ` # Methods` is a paragraph at the top level and a heading inside a list item, where a
    marker would print it; it is left alone, as on `main`, and the paragraph is not compared.
  - *A bullet marker alone over an underline is a list.* `-`, `+` or `*` alone on its line,
    indented up to three spaces, over `===` or `---`, is an empty list item to pandoc, and
    the underline and what follows are its text. `_SETEXT` excluded a marker only with a
    space or a tab after it, so `-` and `+` were taken for a title, the block was passed
    over, and the marker printed inside the list. Such a block is left unmarked whole again,
    as before this change. An ordered marker alone, `1.` or `a.`, is a title to pandoc, and
    passed over like one. The exclusion holds at any indent. Indented four columns or more,
    or by a tab, the lone marker is a title to pandoc at the top level and a nested list
    item under a list, and `_lead_end` cannot see which. So the paragraph under it is left
    unmarked and not compared either way, where at the top level it could have been.
- **A split is recognised by the new text beside it, and that is coarse.** An untagged
  paragraph whose text the document did not have when it was sent makes the tagged paragraph
  touching it a possible split. An edited heading is new text too, so when a heading and the
  paragraph under it are both edited in one round, that paragraph's rewording is refused.
  That is the price of refusing a split, and it does not refuse every one. The search for
  new text stops at the first untagged text the document already had. A table moved with
  its caption between the halves of a split, or a heading dragged there, puts that text
  first, and a tagged paragraph moved there does the same when Word keeps its bookmark -
  which it does for every paragraph but the first of a cut: a line and the paragraph under
  it, cut together without Track Changes and pasted between the halves, stood there with
  the second one's identifier (Word 365, 2026-09-28). Each of these is refused by the
  second half's words instead (see "A move, the way Word makes one"): four words or more
  it lost. That is a judgement. A second half of under four words, or one reworded in the
  same round, still has the paragraph merged as its first half and the rest gone from the
  source, as on main; exit 1, because the second half is listed, but the merge is written.
  A sentence deleted while a paragraph of the same words is added elsewhere is refused the
  same way from four words on: merged, the sentence left the source while the paragraph
  now holding it was only listed, and the words are all that tell it from such a split.
  The maintainer chose refusing it (2026-09-30); under four words it merges. A table, figure or
  equation the
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
- **Some numbers are listed in the annotated copy's appendix and not marked in its text.**
  A number in code, an equation, a link's text or the front matter takes no mark, and nor
  does one inside markup the annotator cannot mark around. Where pandoc reads a paragraph
  differently with its marks in, every mark in that paragraph comes out, not only the one
  that did it: a number in an HTML tag's attribute unmarks its whole paragraph, and a
  hand-written grid or simple table, or a block with attributes, loses every mark in it.
  Each is in the appendix with the reason, but the reader has to look there for it; its
  colour is not on the page. Two code-span edges leave a number unmarked as "in code" that
  pandoc prints outside code: a backslash before a closing backtick, which pandoc does not
  read as an escape, and a backtick left unpaired in one list item that pairs with one in
  the next. Rounds of review of #76 left these, each rare or no worse than on `main`:
  - a link's text across a line break is not found, so its paragraph loses every mark,
    as `main`'s copy misreads it (the extra round);
  - a link's text holding `@` and a number, `[a@b.org room 5](mailto:a@b.org)`, loses its
    paragraph, which `main`'s copy also misreads (the extra round);
  - an escaped `\$` closes an equation to the annotator and not to pandoc, so in
    `from $5 to 7\$` both numbers go unmarked as "in an equation" (the extra round);
  - a number straight after a `]`, `Fees [B]7`, a footnote's marker, `seen[^1]5`, or a
    lone `]`, `x]5`, is left unmarked, where `main` marks it; the rule is for the
    reference two brackets make, and it reaches past them (the extra round). Narrowed,
    it let a mark open on `[^1]$5 `df$a``, where pandoc reads an equation from the `$`
    to one inside the code span, which the annotator does not find: it looks for
    equations outside code (the follow-ups);
  - a range whose backslash is itself escaped, `\\$10-\\$50`, is left unmarked (the extra
    round);
  - a number straight after a TeX command, `\a 5`, is left unmarked: the command took the
    mark for its argument, and the paragraph lost every mark (the final round);
  - reference definitions are looked for one file at a time, so `[Table 2][tbl]` in one
    file, with `[tbl]: #results` in another, has its 2 marked, and the copy the build joins
    prints `Table [2](#mg-n1)` as text, as `main`'s does; "never reads otherwise than the
    manuscript" holds file by file (the fix-only round);
  - a definition on a list item's own line, `- [t]: #x`, which pandoc reads, is not
    found, and a paragraph using it loses every mark, as `main`'s copy misreads it (the
    fix-only round).

  The follow-ups of #76 closed the rest: a number in a link's definition takes no mark;
  definitions are read where pandoc reads one, outside listings and comments, not under a
  paragraph's line, and in a quotation; a bracket alone is a link when its text is defined,
  or a heading's title, and falls back to that over a citation or a note's marker; labels
  are lower-cased as pandoc does, `ß` kept apart from `ss`; a backslash before a letter or
  a digit, `1.2\pm0.3`, `data\2021\05`, `12\²`, reads the same inside a mark; and an
  ordered list's own numbers take none, where marked they made the list a paragraph.
- **The annotated copy prints a manuscript file's own front matter.** The annotated build
  re-reads each source whole, where the build strips its YAML block, so whatever pandoc
  prints from that block prints in the annotated copy and not in the manuscript, its
  numbers listed as "in the front matter".
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
- **`mask()` is quadratic on two inputs no manuscript holds.** A run of `{{` with no `}}`
  on its line, which the placeholder pattern tries from each `{{` to the line's end (2.7 s
  at 32,000 characters), and a long run of backslashes with no `<` or `>` after it, which
  `comparison_escapes` backtracks through from each backslash (about 74 s at 80,000, on one
  machine). Low priority, and not fixed.
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
  from is its sensitivity as well as its cost. Three scans are checked twice, from a small
  start and a large one: paragraph tagging (10 blocks and 1,000), the comment scanner (1,000
  characters and 20,000) and fences whose openers each narrow (5 openers and 25). They are
  tripwires for the scans that went quadratic before, not a proof that nothing else does.
  Each sees only the code its input reaches, and a change elsewhere can route the input
  around that code. Once code spans were read only on a line with a comment or raw-block
  mark, the long run of backticks never reached them, and it passed with the quadratic
  pattern put back. That test now checks that its line is read for code spans. With twice
  as many busy processes as logical CPUs, a scan timed in tens of milliseconds can read
  over the bound: the backtick test did once in five runs, with its comment and without it.
- **A test that times something is found by its syntax, and only in `tests/`.**
  `tests/test_timing_budgets.py` fails when a test reads a clock in `time`, or uses
  `timeit`, outside `check_linear`, unless `tests/data/timing_budgets.yaml` lists it: as a
  budget on a fixed input, saying why a ratio would not do and how much headroom it was
  measured to have, or as a timestamp that times nothing. Like the exemption inventory it
  runs both ways. It also checks that each listed budget is still the number the test holds
  its timing to, as a tripwire for a changed number or constant, not a proof: whether a test
  holds a timing to a number cannot be read completely from its syntax, and four rounds of
  review each found another way past it. It reads comparisons with the timing on either
  side, through names the timing is assigned to, annotated or added to, and a helper's
  timing through every function in its module that calls it by name. Some of what it cannot
  read fails: a caller that holds the timing to nothing it reads, a helper whose timing is
  used from another test module, and a listed constant bound more than once at module
  level. The rest passes unseen: arithmetic done to a timing before it is compared
  (`elapsed / 3 < BUDGET`), a constant shadowed inside the test, a comparison in an `if`
  that only warns or asserted beside an `or`, an assertion made only under an `if`, a
  helper's caller defined under a module-level `if` (a listed test there fails, as no such
  function), a method of a nested class, a helper passed as a value, and a module reached
  from its package (`from tests import test_robustness`, `from . import test_robustness`, or
  `import tests` alone), by its dotted name without `as` (`import tests.test_robustness`),
  or through `importlib` or `sys.modules`. It does not see a clock read any other way:
  `datetime.now()`, `os.times()`, a clock fetched with `getattr` or `importlib`, a module
  bound to a second name (`clock = time`), one in `src/` that a test calls, or a timing a
  subprocess reports. It judges each top-level function whole, so a second timing added to a
  listed test is excused with the first. And a ratio has a blind spot that a budget does
  not: a part of the input that does not grow. If that part alone reaches the 20 ms floor,
  the input is never grown, and the ratio compares two times made mostly of the same
  constant. The attribute-block lines hid `_escaped` scanning back from the start of the
  line that way, behind the one line of eighteen whose run of backslashes is as long at any
  size. So eleven of the seventeen that grow are timed by `check_linear`, and all eighteen
  keep a 5 s budget. The other six are `k=` values whose cost per character steps up at a
  size between the two a ratio compares, so they read 5 to 90 times the time while linear,
  often past a quadratic's 64, and failed correct code one run in six. The headroom was
  measured on one laptop under load.
- **The whole-`check` tests catch a hang or a blow-up, not a scan gone quadratic.** Each
  holds `check` on a hostile project to 30 times a plain `check` on the same project, in
  CPU time, which leaves out G7's wait for Zotero to refuse its ping (2 s on Windows, none
  on Linux) and the time other processes hold the CPU. Load still raises it: on Windows, 48
  busy processes on 24 logical CPUs took readings from about 10 to 18.7, and inside a VM the
  host's load counts as the guest's own, so with 72 busy processes on the host's 24, one
  sample read 55 where about 12 was usual. A ratio between 30 and 60 is measured three times
  more, a plain check then the hostile one each time, and the median of those pairs' ratios
  decides it; the lowest, used before, passed a blow-up of 1.3 to 1.6 times the bound
  whenever one plain run was slowed as much. The median fails a linear input when two of the
  three plain runs fall in a lull deep enough to lift its ratio past 30, about 2.6 times for
  the heaviest. A wall clock backs it up at 60 s, for a `check` that waits instead of
  working, so a wait that returns within about a minute passes, where the old 20 s budget
  failed one of 30 s; one that never returns hangs the suite, as it always did. At the sizes
  these inputs are written at, the heaviest linear ones already cost ten times a plain
  `check` (up to eleven in a Linux VM, and 24 on one round with other suites running), so a
  quadratic that adds a few seconds passes among them. Seeing one is `check_linear`'s job,
  one scan at a time. Two costs fall outside the CPU ratio too: a scan whose result is
  cached by content runs once, on the untimed first check, and garbage collection is off
  while timing. Both are left to the wall clock.

- **G14 reads a definition by its shape, and an abbreviation by its capitals.**
  - A definition written as a sentence is not seen: "hereafter ROR", "which we call the
    ROR", "ROR stands for". Its short form is then reported as undefined.
  - A short form followed by a citation inside the bracket, `(ROR [@key])`, is not read as
    a definition; `(ROR; ...)`, `(ROR, ...)` and `(ROR: ...)` are.
  - Brackets inside brackets are not read: in "(reporting odds ratio (ROR) 3.84)" the inner
    bracket is read and the outer is not, and a definition whose long form holds a bracket
    is missed.
  - The long form is matched by letters, so it can start a word late or early: "the ratio
    as before (ROR)" is read as a definition whose long form is "ratio as before". The
    definition is still counted; the long form quoted in a message can be wrong, and two
    definitions of one thing can be reported as two meanings.
  - An undefined abbreviation with no two capitals together is not reported: `HbA1c`, `mL`
    and `Hb` are missed, where `iPSC` and `siRNA` are caught. `Hb` and `Tregs` cannot be
    defined either, each being the capital of a word, so "haemoglobin (Hb)" is not tracked.
  - Every entry of `data/terms.yaml` is exempt, in any case: it lists `egfr`, `mtor`,
    `ecog`, `nyha`, `meddra` and some 170 more as names, so `eGFR` used and never
    defined is not reported.
  - `II` to `XXXIX` are read as numerals wherever they stand, so `IV` for intravenous and
    `VI` are never reported.
  - A name in capitals is reported like an abbreviation: a trial (`KEYNOTE-189`), a package
    (`SAS`), an agency. The project lists those it means to leave. So are the initials of
    a reviewer named in the Methods, "(JB, CD)", and a US state after a manufacturer's
    town, "Cary, NC". An author's initials are not exempted from `authors.yaml`, because
    initials are two or three capitals and collide with abbreviations: an author named Ada
    Example would hide every `AE`.
  - The formula rule has two edges. A formula with no count is still reported, `HCl`,
    `NaOH`, `KOH`, `HCN`, `NO`, as is organic shorthand, `EtOAc`, `MeOH`, a group in
    brackets, `(NH4)2SO4`, which reports `2SO4`, and a charge, `SO42-`. And a name spelt in
    element symbols with a count from two to twelve is taken for a formula and not
    reported: `PI3K`, `VO2`, `CD3`, `CIN2`, `CKD3`, `PIP2`, `ICD10`.
  - Two abbreviations joined by a hyphen, neither defined, are reported as one: `ROR-PRR`.
  - A defined name is read whole where it opens a hyphenated word, or follows an ordinary
    word or another defined or listed name in it, and not after any other part: in
    `10x-RNA-seq` a defined `RNA-seq` is not counted as used, and with `ChIP-seq` defined,
    `10x-ChIP-seq` is also reported as an undefined `10x-ChIP`.
  - The capital a name takes at the start of a sentence is read one way only, and only
    for an opening word of two letters or more. A name defined with the capital, because
    its definition opens a sentence, "Non-HDL-C (non-high-density lipoprotein cholesterol)
    was ...", is not found by its lower-case uses: they are reported as an undefined
    `HDL-C`, and `Non-HDL-C` as unused. And `T-PA` opening a sentence is not a defined
    `t-PA`, where `Hs-CRP` is `hs-CRP`.
  - A short form in square brackets is read as a definition wherever the words before it
    spell it: a reference link's text, `[ROR][ref]`, and a link to a URL,
    `[ROR](https://...)`, included. A link to a file, `[ROR](glossary.md)`, is not, since
    its bracket is masked with its target.
  - The unit symbols exempt are the nine shipped. `MW`, `MJ`, `MV`, `MDa`, `TWh`, `IU` and
    `HU` are reported: several have a second meaning, and the list is the project's to
    extend.
  - Only a section titled "Abstract" is read apart. A `Summary`, a `Key points` box and a
    `Figure legends` section are main text, so a definition repeated in the Introduction
    after one of them, or in a legend that has to stand alone, is reported as
    `abbreviation-redefined`.
  - A word typed in capitals for emphasis is reported as an undefined abbreviation.
  - Tables and figures are not read, since both are generated from results. An abbreviation
    defined in the text for a table's sake is reported as unused, and one used only in a
    caption is not seen. The hint on `abbreviation-unused` says so.
  - Title-page text comes from `paper.yaml` and `authors.yaml`, which are not read.
  - The sections where nothing is reported as undefined are found by English words in
    their titles: contribution, contributor, acknowledgement, funding, financial support or
    disclosure, competing interest, conflict of interest, declaration of interest,
    disclosure, author statement. A section of the paper proper whose title holds one,
    "Funding of primary care", is quiet too.
  - There is no cap on the number of findings: a manuscript that defines one abbreviation a
    thousand times gets a thousand warnings. Making them is linear in the manuscript.
  - The hook that runs after a manuscript file is saved does not run this gate yet; the
    findings appear at `check`.

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
