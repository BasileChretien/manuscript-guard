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
does with what it receives is in its terms, not in this toolkit. A model that Ollama runs
on your own machine sends nothing anywhere. An Ollama cloud model, one whose name ends
in `-cloud` or `:cloud`, is not one of those: the Ollama server on your machine passes
the request on to Ollama's own servers, and the same goes for any server on this machine
that forwards what it receives. The address is `localhost` either way, so check the
model's name, and what any server at that address does with a request, before you rely
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
comments and with its feasibility results printed into it, and the feasibility results.
Where `paper.yaml` declares a `study_type`, it is also sent what a plan for that design has
to settle, each item with the guideline it comes from: the reviewers ask the plan about
those risks. Not the manuscript, and no result but a feasibility one. Each reply is filed under `review/design/round-<n>/`, and G12 reads it:

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

[Back to the README](../README.md)
