# manuscript-guard

Make every number in a scientific manuscript traceable to its source.

A number in a paper comes from one of three places: your results, the literature, or a
convention of scientific writing. `manuscript-guard` makes that structural rather than
aspirational. Numbers from your analysis are bindings into a machine-written results file,
numbers from the literature are bindings into a ledger backed by stored sources, and
anything else has to be justified. Change the analysis, rebuild, and the manuscript,
supplements and figures follow. A stale number is a build failure, not a discovery made by
a reviewer.

> **Status: early.** The contracts, the number gate and the document build work and are
> tested. The literature tooling, journal compliance, the AI-writing lint and the review
> panels are not written yet. See [DESIGN.md](DESIGN.md) for the plan.

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
manuscript-guard check
manuscript-guard build
```

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
| G11 | a recorded panel has reviewed the manuscript, and its major findings are answered |

`manuscript-guard check --submission` holds the manuscript to submission standards:
unanswered review findings become failures rather than warnings, so you can keep building
drafts to read while the version you send anywhere has to be clean.
| G10 | every figure has a current review by someone who looked at it |

Figures get three checks rather than one. The rendered output is read for numeric text; the
script is checked too, because a script that reads the results and *also* types one
annotation passes an output check today and goes stale tomorrow; and a model or a person
reads the picture, because no parser sees a truncated axis, an unexplained legend, or a
caption describing the figure the author meant to make. That last review is recorded in
`figures/<name>.review.yaml`, and the gate enforces that it exists, covered the required
ground, and applies to the figure as it now stands — not that it was any good.

## Design principles

**The guarantees are deterministic code.** No language model is involved in deciding
whether a manuscript is clean. `manuscript-guard check` runs in CI, offline, and gives the
same answer every time. A separate Claude Code plugin helps with drafting and review, but
it never decides.

**Formatting is fixed where the number is computed.** `display` is set at emit time, so one
quantity cannot be rounded two ways in two sections. Cross-artefact consistency is a
property of the design rather than something checked afterwards.

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
transcription. See [ATTRIBUTION.md](ATTRIBUTION.md) for each guideline's licence as read on
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

```bash
pip install manuscript-guard
```

## Getting started

```bash
manuscript-guard init my-paper
```

Then look at [`example/`](example/), a synthetic pharmacovigilance study that exercises
every gate, including a deliberately awkward case: a value the author read in a printed
agency report that no longer exists online, recorded as an attestation in
`literature/attested.yaml` rather than pretending to a stored source.

Useful when a finding surprises you:

```bash
manuscript-guard explain manuscript/main.md
```

It prints every numeric atom in the file and the rule that classified it.

## Licence

MIT.
