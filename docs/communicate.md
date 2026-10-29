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
anything or opens a connection but three commands, each only when it is run: `lookup
--paper`, which asks Crossref about the paper's own DOI; `communicate publish --post`, which
posts an approved text to Bluesky or Mastodon; and `communicate orcid`, which reads the
authors' public ORCID records.

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
results that bind a value, the limitations the first paragraph that names one under a
heading "Limitations" or "Strengths and limitations" (none where there is no such heading:
write them in), and the conclusion the Abstract's. A heading is no statement. Every finding is written `primary: false`: which one is the paper's primary
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
and `linkedin`, each with its length and where that was read, and a thread of each of the
first two, `bluesky-thread` and `mastodon-thread`, held to its platform's; `press-release`,
the four plain-language summaries, `pitch`, `newsletter`, `blog`, `poster`, `storyboard` and
`video-script`, which tell the whole finding; and `overview`, `data-announcement`,
`researchgate` and `translation-<language>` (`translation-ja`).
`paper.yaml`'s `communication.limits` gives a limit of your own, an instance of Mastodon's.
An entry of `allow:` names a whole sentence as the text writes it, its anchor in or left
out, and allows that sentence only; one with no reason allows nothing, and is said (`comm-allow-no-reason`). A thread is
its posts, each after a line `---` that follows a blank line, each held to the limit; a
mention with its domain (`@alice.bsky.social`, `@alice@example.social`), a hashtag and a
counter that opens a post before a capital or closes one after a stop ("1/5", "2/5" beside
the thread's emoji) are no citation, no number and no claim. A bare `@key` is a citation.
The graphical abstract draws no statement that cites a work in its sentence (`@key`
showed) or points at a display by a LaTeX cross-reference: shorten its text.

A text whose front matter names another language than English by its tag (`language: ja`,
`ja-JP`, `zh_Hant`) is held to its numbers, its bindings, its anchors and its facts, and not
to the words of the claim ladder or to G6, which read English only. Only a tag counts: a
`language` that is `en`, `EN`, `en_US`, `eng`, a word such as `English`, or anything that is
not a tag is held in full.

## Writing the texts

```bash
manuscript-guard communicate build [--channels bluesky,press-release] [--force]
```

writes each channel's text to `communication/<channel>.md`, from the brief alone: the
channels named, else `communication.channels`, else every one it writes. Each sentence it
takes from the brief is the statement's `text`, each of its sentences anchored to the
statement. Each opens with front matter that says what it is:

```markdown
---
channel: bluesky
audience: researchers and the public who follow the authors on Bluesky
version_shared: published
links: ['https://doi.org/10.1234/demo.5678']
attachments: []
---
```

`version_shared` is `published` where the text links the paper, and `none` where it shares
no version of it.

- **Written whole:** the posts and threads of Bluesky and Mastodon (a post drops the
  conclusion where it does not fit, and a thread is a post for each statement), the overview
  slide (`overview.md`, with `overview.svg` beside it, one 16:9 slide drawn as the graphical
  abstract is, each line naming its statement), a poster outline, a storyboard's skeleton,
  the announcement of the deposit, each licence named by its page on the SPDX list (only
  where `package.doi`, a licence and the deposit's `MANIFEST.yaml` exist: with no deposit,
  a build of every channel passes over it and says why, and one that names it with
  `--channels` refuses it), and a translation's scaffold: a slot for each statement, with its
  English and the bindings to keep beside it.
- **Written with slots,** `<!-- write: … -->`, for what only a person or an agent can write:
  LinkedIn (posted by hand: no tool posts there), the ResearchGate summary, a press release, a
  pitch e-mail (a draft: nothing sends e-mail), a newsletter item, four plain-language
  summaries (for the public, patients, clinicians and those who decide policy) and a
  sixty-second script. The statements a slot is about are written below it; the
  research-communication skill says how a slot is filled.

A post and a thread carry no citation and no emphasis: `[@smith2020]` would read there as
a mention of an account, and the marks would be counted against the limit. The long-form
texts keep both, as the brief writes them.

The paper is linked, by its DOI or its URL, only once `publication.status` says it is online;
before that, no text the build writes links it or says it is out. Every text is held to
`communicate check` before it is written, and one the check would fail is not written: the
build says why, and exits 1. A press release, a pitch and the plain-language summaries are
not written from a brief with no limitation in it, and a statement that binds a value
nothing emits stops each text that would carry it, not the others. Only the embargo is not
held against a text the build writes: a text is drafted before the embargo lifts, and the
check fails it until then.

A text that exists is not written over, since it may hold what was written into its slots,
and nor is an `overview.svg` that exists, which may have been edited by hand; `--force`
writes them again. Each run also writes `communication/preview.html`, every text as
it would be read, each binding its display, each slot marked, each post's length against its
channel's, and what the check says of each; and two guides the check does not read,
`communication/guides/lifecycle.md`, what is shared when, and
`communication/guides/researchgate-steps.md`, the steps of adding the paper to ResearchGate by
hand, with what the journal's sharing policy allows there.

## What is due

```yaml
communication:
  enabled: true
  channels: [bluesky-thread, press-release]
  triggers:
    accepted: [press-release, pitch]
    published: [bluesky-thread, mastodon-thread]
    followups:
      - {after_days: 30, channels: [bluesky]}
```

```bash
manuscript-guard communicate status [--prepare]
```

says, for the day it is run, which channels are due, which are written and which wait:
`accepted` from the paper's acceptance, `published` once it is online, and a follow-up from
the day that many days after `publication.published_on`. A text written before the paper was
online, which does not link it, is said to be. Without `triggers`, every channel of
`channels` is due once the paper is online. `--prepare` writes what is due and not yet
written. Nothing runs in the background, and nothing is shared by the tool.

## What may be shared

A text says which version of the paper it shares (`version_shared`: `preprint`, `accepted`,
`published` or `none`) and what it uploads (`attachments`). A document among the attachments,
a PDF or a Word file, is an upload of that version, to the place its channel puts it (`where`
in `channels.yaml`: ResearchGate is an `academic-network`, a blog a `personal-site`); an image
is no version of the paper. Each upload is held to the journal profile's `sharing` block
([journal profiles](journal-profiles.md)): the version recorded there, the channel's place
among its `where`, and its `embargo_months` past since `publication.published_on`, else
`comm-sharing-not-allowed`. Where the profile records no sharing policy, nothing of that
version, or the version or the place cannot be told, `comm-sharing-unknown`. A link to the
DOI is no upload, and is allowed with a policy or without one.

Before `publication.embargo_until`, every text fails (`comm-embargo`). A time given with its
zone (`2026-12-01T00:01Z`, `2026-12-01T09:01+09:00`) lifts at that moment; one without, or a
date alone, is read twelve hours behind UTC, where the day comes last, so that it has lifted
everywhere when it is read as lifted. One that cannot be read as a date and a time is held as
not lifted.

## The paper's DOI

```bash
manuscript-guard lookup --paper [--dry-run] [--again]
```

asks Crossref about `publication.doi`, once, and keeps the answer in
`communication/lookups/crossref.yaml`, with the digest of what it says. Only the DOI is sent.
`communicate check` reads the kept answer and asks nothing: a DOI Crossref did not know warns
(`comm-doi-unknown`), and so does one whose title at Crossref is not paper.yaml's `title`
(`comm-doi-title-differs`), compared with the case, markup, entities, accents, marks and a
subtitle kept apart folded. With no answer kept for the DOI, or one edited by hand, the check
notes it (`comm-doi-not-looked-up`). `lookup --paper` asks again where Crossref did not know
the DOI or did not answer, and with `--again`.

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
| `comm-status-ahead` | fails | the text links the paper's own DOI or URL before `publication.status` says it is online |
| `comm-status-words` | warns | its words read as this paper being out ("our study has now been published", "our new paper is out!", or a headline, "Out now", "Published today, our study ..."), before `publication.status` says it is online |
| `comm-doi-malformed` | fails | a DOI that is no DOI |
| `comm-doi-unknown`, `comm-doi-title-differs` | warn | Crossref did not know the paper's DOI, or gives it another title |
| `comm-doi-not-looked-up` | note | no answer from Crossref is kept for the paper's DOI |
| `comm-embargo` | fails | the journal's embargo has not lifted, or cannot be read |
| `comm-sharing-not-allowed` | fails | an upload of a version of the paper the journal's sharing policy does not allow there, or not yet |
| `comm-sharing-unknown` | fails | an upload where no sharing policy is recorded, nothing of that version is, or the version or the place cannot be told |
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

## Approving a text

```bash
manuscript-guard communicate approve <channel> --as <author>
```

records that an author read the channel's text and approves it as it stands, in
`communication/approvals/<channel>.yaml`: who (`by`), when (`on`), the digest of the text
(`text_sha256`), of the files it attaches (`attachments_sha256`), and that `communicate check`
passed it (`check_clean`). The author is one `authors.yaml` names, by full name, family name,
ORCID iD or e-mail address: the one whose account posts the text. It refuses while the check
fails the text, the embargo apart, since a text is approved before the embargo lifts and
posted after; while a slot is still to write; and, for a Bluesky or Mastodon text, while an
image it attaches is not a PNG, JPEG, WebP or GIF, or has no alternative text.

The digest of the text is of the file and of each post as printed, each binding its display,
and of each image's alternative text. So an edit of the text, of a value it binds, of an
alternative text or of a file it attaches makes the approval stale, and `publish --post`
refuses it until the author approves the text again. An approval is the author's statement:
the hooks put an agent's `approve` to the person and refuse an agent's edit of
`communication/approvals/`.

An image a post carries is named under `attachments`, with its alternative text under `alt`:

```yaml
---
channel: bluesky-thread
attachments: [figure-1.png]
alt:
  figure-1.png: A forest plot of the reporting odds ratio of hepatic injury.
---
```

## Publishing a text

```bash
manuscript-guard communicate publish <channel> [--post [--resume [--was-posted <link> | --not-posted]]]
manuscript-guard communicate publish <channel> --abandon
```

Without `--post` nothing is sent. It writes the exact bodies of the requests `--post` would
send to `communication/outbox/<channel>.json`, with what the service answers, and the moment
each post is sent, in angle brackets, and no credential; writes `preview.html` again; and says
whether `--post` would go ahead, and if not why.

With `--post`, a Bluesky or Mastodon text is posted when, in this order, the journal's embargo
has lifted; `communicate check` fails nothing of it (its own findings, the brief's, paper.yaml's,
and the graphical abstract's where the text attaches it); an author's approval matches the
text as it stands; and the text was not posted on that channel before. The credentials are
read from the environment, never from a file:

| Service | Variables |
|---|---|
| Bluesky | `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` (an app password, made in the account's settings), and `BLUESKY_SERVICE` for an account on another server than bsky.social |
| Mastodon | `MASTODON_BASE_URL` (the instance, `https://example.social`) and `MASTODON_TOKEN` |

Where they are not set, it prints each post, what to paste where and each image's alternative
text, posts nothing and exits 0. A thread is posted post by post, each a reply to the one
before (on Bluesky, to the thread's first post too), and links are marked as links; the
images go on the first post. What the service answered, each post's URI or id, its link and
when, is recorded in `communication/published/<channel>.yaml` as each post goes out. The same
text is never posted twice on a channel, nor the same posts as printed with the same files
attached: a comment added to the file and approved again does not post them again. A thread
that stops part-way, a request refused or unanswered, is recorded as far as it went, and
posting it again whole is refused: `--post --resume` posts the rest, the first of them
replying to the last post recorded. While it stands part-way no other text is posted on that
channel, since an edited thread posted whole would stand beside the first one's posts: put
the text back as it was approved and resume, or run `publish <channel> --abandon`, which
records that the stopped thread is left as it is, its posts up, and lets a new one begin.
The new one must be another text: the same posts as the abandoned thread's, with the same
files, are refused as posted already, and the text is changed and approved again. The posts
as printed include the language they are sent with, so the same words under another
`language` are other posts.

A post sent whose answer was lost is asked for by its key before it is sent again (Bluesky),
or sent again with the same `Idempotency-Key` (Mastodon), so that it is not posted twice.
Mastodon keeps a key for an hour. Within fifty minutes of the post's sending, `--resume`
sends it again with its key; after that it refuses, sends nothing, and says which post may
have gone out and when. Look at your account's page, then:

- `--post --resume --was-posted <its link or id>`, where it is there: the instance is asked
  for that post, which must be the account's, not a boost, made between five minutes before
  the post was sent and an hour after, and reply to the post before it; it is recorded, and
  the rest is posted. Its words are not compared, since Mastodon answers them as HTML;
- `--post --resume --not-posted`, where it is not: it is sent again, under a new key.

`--post` is the author's to run, at a terminal: it posts in public under their name. The
hooks refuse an agent's `communicate publish --post`, as they refuse `deposit --publish`; an
agent may run `publish` without it, and show the author the outbox and the preview. Only a
command the hooks read exactly is refused. One they do not is put to the person instead: run
through a launcher (`uv run`, `pipx run`, `py -m manuscript_guard.cli`), in a subshell
(`( … --post)`), with a `$(…)` anywhere in it, or with a typographic quote anywhere in it. A
flag built from a variable is not seen at all.

The other channels:

- **LinkedIn**: the adapter is deferred, since posting takes an app of the author's that
  LinkedIn reviews. `publish linkedin` prints the text and where to paste it, and posts
  nothing, with `--post` or without.
- **ResearchGate**: there is no interface a tool may post through. `publish researchgate`
  prints the steps, and `publish researchgate --done [--as <author>]` records in
  `communication/published/researchgate.yaml` that they were taken, with the digest of
  `researchgate.md`; with no `researchgate.md` it is refused.
- **A press release, a pitch, a newsletter**: drafts of an e-mail. Nothing sends an e-mail;
  `publish` refuses them.

## Whether the DOI is on the authors' ORCID records

```bash
manuscript-guard communicate orcid
```

asks ORCID's public API, for each author `authors.yaml` gives an ORCID iD, whether
`publication.doi` is among the works on their record, and says so. It sends the iD and
nothing else, reads without a key, and writes nothing, here or at ORCID: a work is added on
the author's own ORCID page. A DOI not found may be on the record and kept private, or shared
with trusted parties only, so its absence may be the author's setting.

## What it does not do

A word list cannot read meaning. "Increased" made "decreased" moves no rung of the ladder; a
sentence with no word of the ladder, no number and no binding needs no anchor; an anchor
proves where a sentence came from, not that it is faithful. The limits of each platform
change, and are recorded with the page and the day. Only an SVG's text is read; a raster's
or a PDF's words are not held to their statements. A translation is held to its numbers and
anchors, not to what its words claim. A link to a copy of the paper elsewhere than its DOI is
not read as sharing it, and the sharing policy is only as good as the page it was quoted
from. Nothing reminds: `communicate status` answers when it is asked, and nothing posts but
`publish --post`, run by the author. A post's Markdown is posted as typed, and a mention or a
hashtag as plain text; Mastodon's limit and its image limits are the instance's; a Mastodon
post whose answer was lost an hour ago is the author's to look for; LinkedIn's adapter is
deferred; the hooks read the commands' text, and a shell write or a direct call of the
library gets past them; and an ORCID
record without the DOI may hold it privately. [DESIGN.md](../DESIGN.md) lists these under
Known gaps.
