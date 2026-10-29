# Communicating the paper: the brief, the graphical abstract and the texts

A post, a press release, a plain-language summary and a graphical abstract each restate the
paper for readers who will not read it. Each is a place where a number can be retyped
wrong, a hedge dropped, an association turned into a cause or a limitation left out, and
none of them passes through the paper's own gates. The `communicate` commands hold them to
the paper: every text is anchored to a brief of the paper's own sentences, and the brief to
the manuscript.

The commands are opt-in. Turn them on in `paper.yaml`:

```yaml
communication:
  enabled: true
```

Without that line every `communicate` command refuses and exits 2. `check` never reads
`communication/`, on or off, so a draft post can never fail the paper. Nothing here sends
anything or opens a connection.

## The brief

```bash
manuscript-guard communicate brief
```

writes `communication/brief.yaml`, the paper's own sentences that every communication of it
restates:

```yaml
schema: communication-brief/1
question:
- id: question.1
  text: Is hepatic injury reported disproportionately often for example-drug?
  from:
    file: design/plan.md
    quote: Is hepatic injury reported disproportionately often for example-drug, relative to all other drugs in the same database?
findings:
- id: findings.1
  text: The reporting odds ratio was {{results.ror.point}} (95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}}).
  from:
    file: manuscript/main.md
    quote: The reporting odds ratio was {{results.ror.point}} (95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}}).
  keys: [results.ror.point, results.ror.ci_low, results.ror.ci_high]
  primary: true
```

Its parts are the question, the design, the population, the methods, the primary outcome,
the findings, the limitations and the conclusion. Each statement's `quote` is a sentence of
the file it names, or several in a row, each whole and word for word; `check` fails one the
file does not hold so, a quote cut from inside a sentence among them
(`brief-quote-not-in-source`). Of a LaTeX manuscript, the words are those of its printed
view, as `check` reads it (a binding written `{{results.key}}`), not the `.tex` as typed. Its `text` is what a communication may say for it: the quote
until you shorten it, and held to the quote as a post is held to the statement.

The scaffold is made the same way every time from the same files. The question, the
design, the population, the methods and the primary outcome are the first sentence under
the analysis plan's heading for each. The findings are the sentences of the Abstract's
results that bind a value, the limitations the paragraph that names one, and the conclusion
the Abstract's. Every finding is written `primary: false`: which one is the paper's primary
finding is yours to mark, and nothing infers it. `communicate brief` will not write over a
brief that exists; `--force` writes it again.

## Anchors

A sentence of a communication that **claims**, one that holds a word of the claim ladder
("associated", "increased", "caused"), a number or a binding, names the statement it
restates by an anchor, which prints nothing:

```markdown
Reports of hepatic injury were {{results.ror.point}} times as likely to name example-drug [](#brief:findings.1).
<!-- brief: limitations.2 --> Spontaneous reports cannot tell us how often it happens.
```

A link with no text, in the sentence or right after its stop, or a comment naming one id or
several. A sentence that claims nothing needs no anchor.

## The texts

Each `.md` directly under `communication/` is a text, with front matter that names its
channel:

```markdown
---
channel: bluesky
allow:
  - sentence: "Example-drug cut hospital admissions by {{results.rr.point}}."
    reason: the trial's primary outcome, as its abstract says it
---
```

The channels are those of `src/manuscript_guard/data/channels.yaml`: `bluesky`, `mastodon`
and `linkedin`, each with its length and where that was read; `press-release`,
`plain-language-summary`, `pitch`, `newsletter` and `blog`, which tell the whole finding.
`paper.yaml`'s `communication.limits` gives a limit of your own, an instance of Mastodon's.
An entry of `allow:` names a whole sentence as the text writes it, and allows that sentence
only; one with no reason allows nothing, and is said (`comm-allow-no-reason`). A thread is
its posts, each after a line `---` that follows a blank line, each held to the limit; a
mention (`@alice.bsky.social`), a hashtag and a counter that opens or closes a post
("1/5", "2/5" beside the thread's emoji) are no citation, no number and no claim.

## The graphical abstract

```bash
manuscript-guard communicate graphical-abstract [--template rct|observational|lab|computational|systematic-review|methods]
```

draws two concepts from the brief into `communication/graphical-abstract/`: `concept-1.svg`,
three panels left to right (what was asked and how, what was found, what it means), and
`concept-2.svg`, the question above its answer. The template follows `study_type`, a trial
`rct`, a cohort, case-control, self-controlled or disproportionality study `observational`,
a prediction model `computational`. The primary finding is set large and the secondary ones
smaller, below a rule; the colours are Okabe and Ito's; every `<text>` names its statement
(`data-statement`) and the values it prints (`data-binding`). The size is the journal's
`graphical_abstract` rule; where its profile gives none, 1328 by 531 pixels, with a note
saying so. Beside the concepts it writes `concept.md`, what each panel holds,
`alt-text.md`, the alternative text, its values by binding, and `validation-report.md`, what
`communicate check --only graphical-abstract` says of them. The concepts are a start for
the author or a designer: draw them again rather than editing their words, since the check
holds each line to its statement.

## What `communicate check` says

```bash
manuscript-guard communicate check [--json] [--only brief|texts|graphical-abstract]
```

Failures are listed apart from warnings, and the command exits 1 on a failure.

| Code | Fails or warns | What it means |
|---|---|---|
| `brief-missing`, `brief-invalid` | fails | there is no brief, or it is not one |
| `brief-quote-not-in-source` | fails | a statement quotes a sentence its file does not hold |
| `comm-number-unbound` | fails | a number is typed where a binding belongs |
| `comm-binding-unknown` | fails | a binding names a value nothing emits |
| `comm-not-reported` | fails | a value the paper reports nowhere |
| `comm-primary-missing` | fails | no finding is marked primary, or a long text or the graphical abstract states none |
| `comm-secondary-as-primary` | warns | a secondary finding leads |
| `comm-claim-unanchored` | fails | a claiming sentence names no statement |
| `comm-anchor-unknown` | fails | an anchor names no statement |
| `comm-fact-not-in-source` | fails | a sentence gives a value, citation or number its statement does not |
| `comm-claim-stronger`, `comm-claim-moved` | fails, unless allowed | a hedge or a limit dropped, a word moved up the ladder from association to cause, a negation gone or new, or both ways at once |
| `comm-claim-weaker` | warns | the sentence claims less than its statement |
| `comm-allow-unused` | warns | the front matter allows a sentence the text no longer holds, or one that claims no more than its statement |
| `comm-allow-no-reason` | warns | an entry of `allow:` gives no reason, and allows nothing |
| `comm-limitation-dropped` | fails | a press release, a plain-language summary or a pitch states no limitation |
| `comm-status-ahead` | fails | the text says this paper is published ("our study", "this paper", "we published"), or links its DOI or URL, before `publication.status` says it is online |
| `comm-doi-malformed` | fails | a DOI that is no DOI |
| `comm-link-temporary` | warns | a link to a shared drive or a bare repository |
| `comm-over-limit` | fails | a post longer than its channel takes |
| `comm-front-matter` | fails | front matter that is not YAML |
| `comm-ga-size`, `comm-ga-aspect`, `comm-ga-words`, `comm-ga-labels` | warn | the graphical abstract against the journal's rules, as G4 warns of a figure |
| `comm-ga-size-default` | note | the journal gives no size |
| `comm-ga-stale` | fails | a line prints a value the results no longer hold |
| `comm-ga-text-not-in-statement` | fails | a line says what its statement does not |
| `comm-alt-missing`, `comm-alt-long` | warn | the alternative text is missing or longer than the journal takes |

The graphical abstract is also held to G4's rules for a figure's file (`figure-format`,
`figure-file-size`, `figure-text-small`), to G3's for its colours and to G3's for its
alternative text (`figure-alt-number`, `figure-alt-binding`). Each text is read by G6 as
printed, each binding its display: a model's artefact fails and the rest warns.

The publication status is `paper.yaml`'s:

```yaml
publication:
  status: accepted        # submitted, accepted, published-online or in-issue
  accepted_on: 2026-11-02
  doi: 10.1234/example.5678
  embargo_until: 2026-12-01T00:01
```

## What it does not do

A word list cannot read meaning. "Increased" made "decreased" moves no rung of the ladder; a
sentence with no word of the ladder, no number and no binding needs no anchor; an anchor
proves where a sentence came from, not that it is faithful. The limits of each platform
change, and are recorded with the page and the day. Only an SVG's text is read; a raster's
or a PDF's words are not held to their statements. [DESIGN.md](../DESIGN.md) lists these
under Known gaps.
