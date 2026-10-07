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

What each model receives is the paper's title, short title, keywords, journal, guideline
and English variant, the journal profile and the reporting checklist where the project has
them, the manuscript as the build prints it, and one reviewer's role, remit and reason.
Not `authors.yaml`, the results files, the figures, or any earlier round: a second round is
blinded because the first round's records are never part of a request. Names written into
the manuscript itself, in the acknowledgements or the funding statement, go with it.

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

[Back to the README](../README.md)
