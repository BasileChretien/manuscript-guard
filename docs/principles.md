# What the check guarantees, and the principles behind it

The table of gates is in the [README](../README.md#what-is-checked). The reasoning behind
each choice, and an honest list of what the toolkit cannot do, is in
[DESIGN.md](../DESIGN.md).

## What the check actually guarantees

The check reads your **source**, where bindings are still visible, not the rendered output
where every number looks alike. That makes the rule simple and hard to slip past:

> In manuscript source, a bare numeric literal is a defect unless it is a recognised
> convention or a structural reference.

A results-derived number cannot be written as a literal at all, so nothing passes by
coincidence. The check also runs backwards: a value your analysis declares as quoted, which
no source file references, is a failure too. A registry that binds a handful of numbers and
reports "all clear" is worse than no registry.

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

`check` asks whether anything has been *disturbed*, and that is a question about digests —
which can be recomputed. `verify` asks a different question: it re-runs your analysis into a
scratch copy and compares the fragments value by value. A digest can be forged; a result
cannot be forged into existence. It is a separate command because it executes your code,
which a gate must never do, and because it takes as long as the analysis does. The digests
are of the script that wrote a results file and of the inputs it declared: a module that
script imports fails the run only where it is listed among the `inputs`. Left unlisted, a
source file under `analysis/` that is newer than the results is a warning, and only
`verify` shows that a value changed.

## Design principles

**The guarantees are deterministic code.** No model output is trusted as evidence about the
text. `manuscript-guard check` runs in CI, offline, and gives the same answer every time.
A separate Claude Code plugin helps with drafting and review, but it never decides.

Two gates are a partial exception, and it is deliberate rather than accidental: G10 and G11
read a *recorded* review, and a review record classifies its own findings by severity. A
finding recorded as `fail` fails the run; the same observation recorded as `info` does not.
The record is the contract — a model may write one, and a person answers its major
findings. No gate asks a model anything. One command does, when you tell it to: `review
--run` sends the manuscript to the models you list and files what each says as such a
record, which G11 then reads like any other.

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
package, and a recipe of the same name in your project overrides the shipped one. See [ATTRIBUTION.md](../ATTRIBUTION.md) for each guideline's licence as read on
2026-08-03 — one of them is non-commercial, and several state no reuse licence at all.

Recipes ship for thirteen checklists: STROBE, RECORD, RECORD-PE, CONSORT, SPIRIT 2025,
PRISMA 2020 and its abstracts checklist, READUS-PV and its abstracts checklist, TRIPOD in
its three variants, and ARRIVE 2.0; and for one instrument that is not a checklist, SANRA,
the scale a narrative review is appraised with. You supply the official document; the profile
is generated locally. Each profile records how thoroughly it was verified, because that
differs — a Word table allows every item's full text to be checked, a column-laid-out PDF only
each item's opening clause, and a rating scale read line by line allows no independent check
at all, offering instead that a line it cannot place stops the transcription, as far as the
counts a recipe states can see.

The transcribed text is not redistributed, so each guideline's licence stays the guideline's
business.

A guideline you have named but not retrieved fails loudly rather than passing quietly.

**The AI-writing lint measures rate, not presence.** It catches model artefacts outright
(`oaicite`, `[cite: 1]`, unfilled placeholders) and warns on well-catalogued phrasings, but
for ordinary words it counts. "Robust" describes a standard error and "significant" has a
technical meaning; six "crucial"s in four hundred words is the tell, not one. A lint that
flags robust standard errors gets switched off, and a lint that is switched off guards
nothing. It detects **habits, not authorship**, and says so.

**Abbreviations are checked against the manuscript itself.** Whether "CI" needs defining is
a journal's decision; whether an abbreviation was defined, defined twice, defined for
nothing or used before its definition is a fact about the text, the same in any field.
G14 reports those four as warnings, reads the abstract, the main text and the supplement
apart, and takes the abbreviations a paper leaves undefined on purpose from
`language: known_abbreviations:` in `paper.yaml`.

**One term for one thing is declared, not guessed.** "Participants" in the Methods and
"subjects" in the Results reads as two groups. Which word is right is the author's call,
so the author declares it, under `language: vocabulary:` in `paper.yaml`, with the words
given up for it, and G14 reports each of those the manuscript still uses. It has no list
of synonyms of its own.

**One English, the one the paper declares.** `english_variant` in `paper.yaml` says
British or American, and G14 reports the words spelt the other way: "color" in a British
paper, "randomised" in an American one, and both `-ise` and `-ize` in a British one. A
name keeps its spelling, and so do a quotation, the reference list and the sections whose
wording is somebody else's: contributions, acknowledgements, funding and competing
interests, where the role names are CRediT's and a funder's sentence is the funder's. The
list of words is derived from [VarCon](http://wordlist.aspell.net/): from the part of it
that was verified against dictionaries, and from the rest only verbs in `-ise` and a few
medical forms such as `haem-`. Where a field spells a word its own way, the project lists
the word under `language: accepted_spellings:`.

**One notation, the manuscript's own.** Whether a P value is a capital italic *P* or a
lower-case p, and whether an interval runs "1.2 to 3.4" or "1.2-3.4", is a journal's to
say. That the manuscript writes each one way is the manuscript's, and G14 reports the
form used less: for the symbol of a P value, the spaces around the sign after `P` or
`n`, what joins the bounds of an interval, and the space before "%". A bound value
counts as a number, so the notation around `{{results.p}}` is read like any other. One
thing is no matter of counting: a number that runs into its unit, "5mg", is reported
wherever it stands, because the SI Brochure sets a space there.

**A language edit changes the wording and nothing else.** A co-author, an editing service
or a model that tidies a paragraph is trusted with its words, and `check` cannot see
whether it kept to them: one confidence bound written for the other is still a binding
that resolves. `manuscript-guard reworded` compares the manuscript with the last commit and
holds every binding, every citation key and every typed number to its place. One that is
gone, new or changed fails. The same ones in another order pass with a warning for each
place, because a clause that moved and two values that changed places look the same. A
number is compared as it is typed, so "3" spelt out as "three" is reported too; the space
before a unit or around a sign is free. A minus sign is part of its number where the dash
can be nothing else; where it may be the dash of a range, after a mark of emphasis or a
raised figure, one that came or went is shown with a warning.

**Exemptions are small, explicit and reviewable.** Conventions live in a narrow shipped
list pinned to specific values — `p < 0.05` is allowed, `p < 0.37` is not, because a p-value
you obtained is a result. Project additions require a written reason. Axis ticks are
declared per figure in a sidecar.

**The analysis language is yours.** The toolkit needs a results file, not a particular
language. Emitters exist for Python and R; anything that can write JSON can take part.

[Back to the README](../README.md)
