# manuscript-guard — design

Status: design agreed 2026-08-03. **All eight phases built and tested.** 558 tests pass,
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
- One chore remains in the build pipeline: no `ZOTERO_PREF` or `ZOTERO_BIBL` field is
  emitted, so document preferences and bibliography insertion are manual unless we inject
  them. (Narrative `@key` citations also produced no field at the time of this note; that
  was fixed with `author-in-text: true` — see "The build" below.)
- **Zotero's local API (`/api/`) is disabled** on this machine — returns
  `403 Local API is not enabled`. Not needed: **Better BibTeX's JSON-RPC works** and
  returns CSL-JSON including citation keys.
- **Zotero replies HTTP/1.0 with a close-delimited body.** .NET's HTTP client rejects this
  (`response ended prematurely`); Python's `urllib` handles it. All Zotero access must go
  through Python, never PowerShell.
- **The agent tool sandbox blocks localhost.** Any step touching Zotero needs the sandbox
  disabled, which has consequences for how hooks are written and permissioned.
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
  r/manuscriptguard/   # emit() -> results.json with provenance
  plugin/
    skills/  agents/  hooks/  commands/
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
  figures/              # scripts that may read results.json and nothing else
  build/                # docx/pdf artifacts, gitignored
```

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
| G11 | Panel review | no review round, a stale review, or an unanswered major finding |
| G12 | Methods appropriateness | the analysis plan does not answer the question asked |

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
   attested, authors, paper. `emit()` in Python and R with provenance stamping. Gate G1.
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
  CSL style. Citations become formatted text rather than live fields. This is what CI and a
  co-author without Zotero get, and it is why the `.bib` is committed rather than exported
  on demand. `manuscript-guard sync-bib` rewrites it from Zotero, containing exactly the
  keys the manuscript cites.

`zotero.lua` is fetched and cached under `build/.cache/` rather than vendored: it belongs to
Better BibTeX and tracks its behaviour, so a pinned copy would go stale.

After a live build the document is reopened and its Zotero fields counted, because the
filter fails quietly when Zotero is closed — the result looks fine until someone clicks
Refresh in Word and every citation vanishes.

**Tables are emitted, not written.** `em.table(...)` puts a table in the results fragment,
`{{table.key}}` places it, and the build renders a pipe table. A hand-typed table is the
most reliable place for a stale number to survive: long, dull to re-read, never diffed. An
emitted table nothing places is a coverage failure, exactly like an unquoted value.

**Figures are placed, captions are prose.** `{{figure.key}}` resolves to the rendered file,
preferring raster or PDF over SVG because Word's SVG support is uneven and a journal's
production system is worse. The caption stays in the manuscript as ordinary prose, so it is
checked like prose and can carry bindings.

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
references counted separately; headings counted, because they are printed. Counting is done
on the source rather than the built document, so a binding counts as one word whatever it
resolves to and the count does not move when the analysis is re-run.

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

Editing the manuscript changes its digest and marks the reviews stale, which is correct: a
review of the old Results is not a review of the new ones.

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
  reading it raw reports corrections as errors and misses what will be published.
- **The bibliography dropped.** Recognised by heading where there is one and by entry shape
  where there is not, because citeproc appends a reference list with no heading to cut at.
  Otherwise every volume number and page range is reported.
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
  `zotero` and the rest of the machinery stay masked.

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
  every threshold rule beneath it. Anchored at both ends now.
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
  lives in a bracket.
- **Table captions and column headers were checked by nothing** — not by the emitter, not by
  `verify`. Both render with the table.

And `verify` had three of its own, of which one was serious enough to invalidate the
command: see its module docstring for what it now does and does not prove, and the Known
gaps below for what remains.

## Known gaps

Recorded because a gate whose limits are undocumented gets trusted beyond them.

- **`verify` cannot hide from the code it runs.** The two easy tells are gone — no
  environment variable, no `manuscript-guard-verify-` in the scratch path — but a script can
  still notice it is running under the system temp directory. An analysis written to deceive
  its own toolkit defeats this; an author who edited a results file does not.
- **A figure render manifest is a drift detector, not a proof.** `<name>.render.json` sits
  beside the figures it vouches for and is writable by whoever holds the checkout: retouch
  the raster *and* rewrite its digest and G3 skips it again, exactly as a `.sha256` can be
  recomputed. It catches the ordinary case — a raster re-rendered on its own and left beside
  a fresh vector — which is how the wrong figure actually reaches a journal. There is no
  `verify` equivalent for figures, because re-rendering is not reproducible across
  plotting-library versions.
- **A figure review covers the vector, not the raster that ships.** `content_sha256` is
  over the file G10 could read; the .docx embeds the raster.
- **The composite-cell rule is set membership.** A cell of "ROR 5.12 (95% CI 3.84 to 2.89)"
  passes if 5.12, 3.84 and 2.89 are all emitted values, whatever they mean — the point
  estimate and both bounds can be transposed. `em.cell()` composes cells correctly; nothing
  forces its use.
- **Setext headings are not recognised.** A manuscript written with `Methods\n-------` has
  no sections at all as far as G2, G4 and the reporting gate are concerned. Pandoc renders
  them.
- **G2 is loud on Methods prose containing code.** Unmasking fenced blocks means a
  legitimate `## Statistical analysis` section quoting `1.96`, a seed, or a package version
  produces failures, and there is no `software-version` structural rule. The documented exit
  is `conventions:`, which is the mechanism most likely to make G2 vacuous — so this is a
  real cost of a real fix, not a clean win.

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
Closed since, and why each mattered:

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

- **The emitter had no invariants.** `display` was returned verbatim, so one call could
  publish a fabricated estimate *and* a fabricated interval; table cells were `str()`-ed and
  compared to nothing, so "tables are emitted, not written" was satisfied by calling the
  emitter while the numbers stayed typed. A display must now render its own value, and a
  numeric cell must be a number. A composite cell — "3.84 (2.10 to 7.02)" — stays a string,
  but every *claim* in it must be a value the analysis published, with the manuscript's own
  classifier deciding what counts as a claim so "Age 18-44" is a label in a table for the
  reason it is one in a sentence. `em.cell("{} ({})", n, (pct, 1))` covers "n (%)", because
  an f-string reaches `table()` indistinguishable from a typed string and the API has to be
  the thing that tells them apart. Both rules are mirrored in the R emitter: the fragment is
  a cross-language contract, and a rule enforced on one side is one an author steps around
  by switching language.
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
- **Nothing checks that the built .docx matches the source it was built from.** A stale
  `build/manuscript.docx` sitting beside changed sources is not reported; rebuilding is
  cheap, but the gap is real.
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
- **The plugin is installed by symlink, not from a marketplace.** No marketplace manifest
  exists yet, so installation is a manual link into a skills directory.
- **The audit cannot tell where a number should be, only whether it exists somewhere.** A
  value correct in the abstract and wrong in the Results passes, as does a number matching
  a coincidental value in an unrelated output. It is triage for existing work, not a
  guarantee.
- **A thousands separator written as a space is read as two numbers.** "41 200" becomes 41
  and 200, because atoms are split on whitespace. Non-breaking spaces are handled; ordinary
  ones are not distinguishable from a sentence break.
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

## Still open

- Who reviews additions to the per-project convention allowlist, and whether entries need
  a written justification. The schema already requires a `why`; nothing enforces review.
- Cross-platform hook portability. Only Windows is available for testing, so CI runs
  Ubuntu and macOS.
- Zotero group library support, and behaviour when a citation key is pinned in one library
  and absent from another.

Resolved 2026-08-03: the pre-analysis design gate **warns rather than blocks**, so
exploratory work stays possible.
