# A review panel read by several models

G11 asks that a recorded panel has read the manuscript and that its major findings are
answered. The panel can be people, an agent, or models from several providers. The last is
worth having because a panel read by one model shares that model's blind spots.

List the models once in `paper.yaml`, each as `provider/model`. The model names are yours
to supply, from each provider's own list:

```yaml
review:
  models: [openai/<model>, mistral/<model>, moonshot/<model>]
```

```bash
manuscript-guard review --providers       # the providers, each key's variable, set or not
manuscript-guard review --run --dry-run   # what would be sent where; sends nothing
manuscript-guard review --run             # the same statement, then asks, then sends
manuscript-guard review                   # who read what, and what is still open
```

Built in: OpenAI, Mistral, Moonshot (Kimi), DeepSeek, OpenRouter, Google's Gemini endpoint,
Anthropic, and a model on your own machine through Ollama. Each key is read from its
environment variable, which `--providers` names, and is never written to a file, a record
or a message. Any other provider that speaks the same chat API is added by its address:

```yaml
review:
  models: [lab/<model>]
  providers:
    lab:
      base_url: https://llm.example.org/v1
      key_env: LAB_API_KEY
```

**Your manuscript is unpublished, and sending it to a provider is your decision.** Before
anything is sent, the command says which files go to which host and how many calls that is,
and waits for you to type yes. `--dry-run` shows the same statement, writes the exact
requests under `build/` for you to read, and opens no connection. What a provider keeps or
does with what it receives is set by its terms, not by this toolkit, and [What a provider
keeps](#what-a-provider-keeps) says what each one's terms said when they were last read. A
model that Ollama runs on your own machine sends nothing anywhere. An Ollama cloud model,
one whose name ends in `-cloud` or `:cloud`, is not one of those: the Ollama server on your
machine passes the request on to Ollama's own servers, and the same goes for any server on
this machine that forwards what it receives. The address is `localhost` either way, so check
the model's name, and what any server at that address does with a request, before you rely
on it.

**Where the data custodian restricts where the manuscript may go,** say so in `paper.yaml`:

```yaml
custodian:
  restricts_sending: true
```

`review --run` then sends to a model the built-in Ollama runs on this machine, and to any
other provider only once the data custodian has authorised that provider: a provider you add
under `review.providers` needs it even at `localhost`, since it may be a router or a tunnel. Name them in `authors.yaml` (`roles:
data_custodian:`, an author or `name:` someone who is not), and they authorise each
provider themselves: `manuscript-guard sign --as "<them>" --finding
G11/custodian/send-to/<provider>`. The authorisation is of the provider at its address: a
provider pointed somewhere else, or an Ollama cloud model, wants it again. Until then a run
sends nothing and says who authorises what; a dry run writes the requests, for the
custodian to read before deciding.

What each model receives is the paper's title, short title, keywords, journal, guideline
and English variant, the journal profile and the reporting checklist where the project has
them, the manuscript as the build prints it, and one reviewer's role, remit and reason.
Not `authors.yaml`, the results files, the figures, or any earlier round: a second round is
blinded because the first round's records are never part of a request. Names written into
the manuscript itself, in the acknowledgements or the funding statement, go with it.

**A design round is read the same way, before there are results.** `manuscript-guard
review --design --run` sends each reviewer of `review/design/panel-<n>.yaml`, or of a starter
design panel in the first design round, the paper's facts, `design/plan.md` without its
front matter and comments and with its feasibility results printed into it, and the
feasibility results.
Where `paper.yaml` declares one of the seven designs as its `study_type`, it is also sent
what a plan for that design has to settle, each item with the guideline it comes from: the
reviewers ask the plan about those risks. With `study_type: other` nothing of the kind is
sent. Where the project keeps `design/methods_review.yaml`, the methods of similar
studies are sent too, each in the study's words with its appraisals and the author's
decisions, for the reviewers to check each appraisal against its standard; a reading's digest
holds the record, so one changed since is stale. Not the manuscript, and no result but a feasibility one. Each reply is filed under `review/design/round-<n>/`, and G12 reads it:

```bash
manuscript-guard review --design --run --dry-run   # what would be sent where; sends nothing
manuscript-guard review --design --run             # the same statement, then asks, then sends
manuscript-guard review --design                   # where the design rounds stand
```

Two warnings follow from that. G11 says when every reading of a round came from one provider
(`round-one-provider`), since one provider's models share their blind spots, and when a model
passed a remit that covers the figures it was never sent (`figures-not-seen`). A finding may
say what it asks of the authors (`ask`: `disclosure`, `computation` or `new-data`); an open
major finding that asks for a computation says so, since it is a new result to emit.

By default every model reads every reviewer's remit; `--one-each` deals one model to each
reviewer in turn. With no `review/panel-N.yaml`, the first two rounds use a starter panel
that assumes no field, which you can then edit. Each reply has to be one object of a fixed
shape or it is refused: nothing a model wrote is repaired, and a refused reply is kept to
read under `review/round-N/refused/`, where no check counts it. The panel file names every
reader that was asked, so a round in which one provider failed shows as incomplete, and
running the command again asks only for what is missing.

A model files a review record; its verdict decides nothing. Its reading does count: it
completes that reader's part of the remit, and the severity it gives each finding decides
which ones bind. G11 reads the records as it reads one written by hand: every major
finding, from any reader, has to be answered with a `resolution` or an `overridden`
before a submission build. A reading made by hand or by an agent counts beside the
models' (`manuscript-guard review --record <reviewer> --round <n> --reading <who>
--verdict <verdict>`).

What the reader wrote is sealed: a filed reading carries `reading_sha256`, a digest of
its verdict, summary, rejection tests and findings, and a finding made minor, reworded or
deleted afterwards is `reading-altered`, which fails a submission. The answers are not in
the seal. A model's reading is sealed when it is filed; one written by hand is sealed
once its findings are in, with `manuscript-guard review --seal <reviewer> --round <n>`
(and `--reading <who>` for a named reading).

**Each finding quotes what it is about.** A reader given only the title and abstract raised
every defect the example's first panel found, so a finding is no evidence that the paper was
read. A finding gives `quote`: at least four words copied from the manuscript, or for
something missing the heading of the section where it belongs. When the reading is filed,
each quote is looked for in what the reader read: by `review --run` in the manuscript as
each model was sent it, its values printed, and by `review --seal` in the files whose
digests the reading carries, as they are written and as the build prints them. It is found
as G7 finds a quote in a source, whatever the white space, curly quotes, dashes and
Markdown's marks, a link read as its text, as whole words and in order where words are left
out with "..."; a piece between elisions counts towards the four words only with two words
or more. What was
found is kept as `quotes`, sealed with the reading. `check` and `review` count the anchored
and unanchored findings apart, and a reading with unanchored findings is a note
(`finding-unanchored`) at every stage; an unanchored major finding is still to be answered.
A model must quote, so its finding with no quote is unanchored; a person may leave one out.
Where a file the reading read has changed before it is sealed, the quotes are not looked
for, and the seal says so. A design round's readers are not asked to quote.

**`review` shows which readers quote one sentence.** With each anchored quote, the reading
keeps the sentence it stands in and the section over it, found and sealed when the reading
is filed: a heading's title is at its heading, a quote across two sentences at both, and one
whose words stand twice, in the abstract and in the Results, at each. Under each reading,
`review` shows the sections its quotes fall in (`quotes in: Abstract 5, Methods 1`); under
each round, every sentence two readers or more quote, with the readers and their findings,
each reader counted once however many remits it read. It decides nothing, and it groups
places, not problems: readers who quote one sentence may each be saying something else.
Readings sealed before places were kept are counted and not placed.

**A finding can carry the wording it asks for, and you decide it in Word.** A finding may
hold `edits`: the manuscript's words as they stand (`old`, enough of them to appear once in
its prose) and the words to put in their place (`new`). Every model is offered this, ten
edits a reading at most; a reading written by hand or by an agent can hold them too, before
it is sealed. They are sealed with the reading, so an edit changed afterwards is
`reading-altered`.

```bash
manuscript-guard review --suggestions --round 2
```

writes `build/suggestions/round-2.docx`: the document as `build --offline` prints it, each
edit a Word tracked change under its reader's name, with its finding as a comment. It is
for you, not for the journal. An edit is written only where it can be placed exactly: its
words found once in the manuscript's prose and once in their paragraph as the build printed
it, in a paragraph the round trip brings back, holding no markup, and changing no number,
binding or citation, which is the rule `reworded` holds a rewording to. Emphasis, code or a
link beside the words stays as it is, and emphasis around them goes round the new words, as
Word shows them; words that cross the edge of the markup, or would make the paragraph read
otherwise than Word shows it, are not written. Each one that is not is listed with the
reason, and stays a finding to answer in its record.

In Word, accept or reject each change. To refuse one with a reason, reply to its comment.
Then:

```bash
manuscript-guard import build/suggestions/round-2.docx --apply
```

`import` refuses the document while any of the panel's changes is undecided. The accepted
words are written into the source where the edit found them, so the markup beside them
stays; anything else you changed in that paragraph is merged as any rewording from Word is.
Where the words can no longer be written there exactly, the paragraph is refused with the
reason. Each finding is answered in its record: an accepted edit becomes its `resolution`, dated; a refused one with your
reply becomes its `overridden`, with the reply as the reason and its author as
`overridden_by`. A refused edit with no reply leaves its finding open, since turning down a
wording does not answer what the finding says. Nothing in the reader's words changes, so the
seal still holds.

## What a provider keeps

Once a request has arrived, what the provider keeps of it and what it does with it are set by
its terms, and the terms change. The table is what each built-in provider's own pages said on
2026-11-14 of an account that has a key and no agreement beyond the standard terms, with the
name `review: models:` gives the provider in brackets. An agreement your university or company
has signed with a provider may say otherwise. Read the pages before the first run, and again
when you add a provider.

| Provider | Kept by default | Used to train models | Keeping nothing | Its pages |
|---|---|---|---|---|
| OpenAI (`openai`) | up to 30 days, in the logs kept to watch for abuse | no, unless you opt in | zero data retention, once OpenAI has approved it | [Data controls](https://developers.openai.com/api/docs/guides/your-data) |
| Anthropic (`anthropic`) | deleted within 30 days; a request flagged under the usage policy up to 2 years, and its safety scores up to 7 | no | zero data retention, once Anthropic has approved it for the organisation | [Retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data), [Zero retention](https://privacy.claude.com/en/articles/8956058-i-have-a-zero-retention-agreement-with-anthropic-what-products-does-it-apply-to), [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) |
| Gemini (`gemini`) | 55 days, for abuse monitoring, paid or not | on a project with no billing account, yes, and human reviewers may read it; with billing, no | none found | [Terms](https://aistudio.google.com/docs/terms), [Usage policies](https://aistudio.google.com/docs/usage-policies) |
| Mistral (`mistral`) | as long as the agreement runs, and for 30 days after it ends; in the EU unless you use the US endpoint | the pages differ: the commercial terms rule it out except in the cases they list, the data processing addendum trains on it "unless Customer is or has opted-out", and the help centre gives pay-as-you-go a switch to opt out | zero data retention for stateless API calls on pay-as-you-go, which is what `review --run` makes, on request and at Mistral's discretion | [Commercial terms](https://legal.mistral.ai/terms/commercial-terms-of-service), [Data processing addendum](https://legal.mistral.ai/terms/data-processing-addendum), [Where data is stored](https://help.mistral.ai/en/articles/347629-where-do-you-store-my-data-or-my-organization-s-data), [Opting out of training](https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training), [Zero retention](https://help.mistral.ai/en/articles/347612-can-i-activate-zero-data-retention-zdr) |
| DeepSeek (`deepseek`) | "as long as necessary", on servers in the People's Republic of China | yes; its privacy policy lets you refuse, by writing to it | none found | [Privacy policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html), [Platform terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) |
| Moonshot outside mainland China (`moonshot`, `kimi`) | while the account is open, on servers in Singapore | yes, unless an enterprise agreement says not | zero data retention for enterprise customers, on request | [Platform terms](https://platform.kimi.ai/docs/agreement/modeluse), [Privacy policy](https://platform.kimi.ai/docs/agreement/userprivacy), [Zero retention](https://platform.kimi.ai/docs/guide/zero-data-retention.md) |
| Moonshot in mainland China (`moonshot-cn`) | as long as the service needs it, in mainland China, under its law | yes: its service agreement takes a free licence to use what you send and what it returns to improve its models; no way to refuse found | none found | [Service agreement](https://platform.kimi.com/docs/agreement/modeluse), [Privacy policy](https://platform.kimi.com/docs/agreement/userprivacy), both in Chinese; `platform.moonshot.cn` now leads there, and neither page names `api.moonshot.cn` |
| OpenRouter (`openrouter`) | its privacy policy does not say it keeps nothing, and says personal data in what you send is collected; the provider it passes the request to keeps what that provider's terms say | not by OpenRouter; some of the providers it passes requests to do | routing to zero-retention endpoints only, which you can require for the account | [Privacy policy](https://openrouter.ai/privacy), [Privacy and logging](https://openrouter.ai/docs/features/privacy-and-logging), [Zero data retention](https://openrouter.ai/docs/features/zdr) |
| Ollama cloud (`ollama`, a model whose name ends in `-cloud` or `:cloud`) | not kept beyond the request, its privacy policy says; some models are hosted by partners it holds to no logging | no | nothing to ask for, since it says it keeps nothing | [Privacy policy](https://ollama.com/privacy), [Cloud](https://ollama.com/cloud) |
| Ollama on your machine (`ollama`, any other model) | nothing leaves the machine, unless the server there passes it on | no | nothing to ask for | none needed |

Three things in it are easy to miss.

- A Gemini key from a project with no billing account is the unpaid service. Google uses
  what it is sent to improve its products, and its human reviewers may read it. Its terms
  put free use from the European Economic Area, Switzerland and the UK under the paid terms.
- Where zero data retention needs the provider's approval (OpenAI, Anthropic, Mistral, and
  Moonshot outside mainland China), it is agreed account by account. Until the provider has
  agreed it for yours, a request is kept as the second column says.
- OpenRouter passes each request on to another provider, whose terms then apply.
  `review --run` sends no routing instructions, so set it in your OpenRouter account's
  privacy settings: route to no provider that trains on what it receives, or only to
  zero-retention endpoints.

Where the data custodian decides which providers the manuscript may go to, the table and its
pages are what to show them.

## Comments a co-author left in Word

A co-author's comments are not a panel's reading, and they are not lost either. `import
--apply` files each comment of a returned document in
`review/comments/<manuscript|supplementary>-<build>/<commenter>.yaml`, outside every round:
the comment word for word, its replies, the words it was made on and its paragraph. G11
reports each one until it has a `resolution` or an `overridden` reason, whatever its
severity, and `check --stage submission` fails while one has neither. The records are sealed
like a reading, so a comment reworded or deleted by hand is `comments-altered`, and they
never go into a build or the submission pack. The word-roundtrip skill has the details.

[Back to the README](../README.md)
