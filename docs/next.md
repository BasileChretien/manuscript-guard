# What to do next

`manuscript-guard check` says what is wrong. It does not say which of forty findings to
start with, or that a choice is due that no finding names. `manuscript-guard next` runs
every gate once, as `check` does, and says what to do now, in a fixed order, with the skill
that deals with it and the exact command:

```bash
manuscript-guard next              # the first three actions in full, then the rest by title
manuscript-guard next --all        # every action in full
manuscript-guard next --json       # the same decision, for an agent
manuscript-guard next --stage internal-review   # decide as at another stage
```

It writes nothing. It exits 0 once it has decided, whatever it found: `check` is the command
whose exit says pass or fail. It is advice, and the order is a rule, upstream first: the
results come before the numbers bound to them, and the plan before the numbers that answer
it. Nothing `next` says makes a finding pass or fail.

## The order

Each action comes from one rule, and the rules are tried in this order (`guide.RULES`).
Within a tier, actions go in gate order, upstream first, then by code, file and line.

| Tier | Rule | What it says |
|---|---|---|
| 0 | `cannot-check` | the project's files cannot be read, or a gate could not run (`gate-errored`, `manuscript-unreadable`, `schema-violation`, `duplicate-key`) |
| 1 | `start` | there is no project: start one, from a paper in the folder where there is one (`init`, `init --from`, `init --latex`, or only `audit`) |
| 2 | `stale-results` | G1 fails: the results are not what the analysis makes now |
| 3 | `plan` | G12 fails: the analysis plan |
| 4 | `choose-journal`, `choose-english`, `choose-guideline`, `choose-study-type` | a choice is due, offered as the `set` commands to pick from |
| 5 | `provenance` | G2, G3, G7 or G8 fails: a number has no source. A number that reads as exactly one published value is offered as its own `bind --apply --only FILE:LINE` |
| 6 | `failures` | everything else that fails, by code |
| 7 | `co-author-checks` | from `internal-review`, a round of co-authors' checks is open: answers outstanding, stale or in disagreement |
| 8 | `warnings` | warnings, one action for each skill |
| 9 | `advance` | nothing fails now: see what the stage after the one `paper.yaml` declares asks (`check --stage <next>`), or ask the author to move to it (`set stage <next>`). A view of an earlier stage (`--stage`) offers no move |
| 10 | `optional` | nothing fails, from `internal-review` on: the review panel, a co-author's page, the build, the package, approvals, and at `submission` the pack and the proof |

A choice is due when a finding asks for it (`journal-profile-missing`,
`english-variant-undeclared` or `-mismatch`, `reporting-guideline-for-design`), or from
`drafting` when the setting is not made: no `target_journal`, no `english_variant`, no
reporting guideline. The study design is due wherever `study_type` is not set. A finding a
choice answers is in that choice and is not listed again.

A finding's code decides its skill and its command (`guide.ROUTES`): its own entry, or the
longest prefix it begins with. A code no entry names is sent to its gate's skill with
`check`; it is never dropped. On a LaTeX manuscript the co-author checker and the proof are
not offered, since neither reads LaTeX yet, and a note says so.

## Who runs it

Every action and every option says who runs it, in `who` in the JSON and in the text: an
action's `run:` line ends "(the author runs it)" or "(ask the author first)", an author's
action with no command has a line saying so, and an option ends "; the author runs it" or
"; ask the author first":

- `agent`: an agent may run it;
- `author`: the author decides it, or runs it, as `approve` is the author's own act;
- `ask-author`: an agent runs it only after the author has said yes to that command, as for
  `review --run`, which sends the paper to model providers, `bind --apply`, which writes
  into the manuscript, `set stage`, or another journal or English than the one declared.

A finding only a named person may answer, an attestation, a judgement of a passage, a
methods decision, an approval, a sign-off, a person's reading of the figures, or a
reviewer's or co-author's finding left as it stands (whose record names who decided), is the
author's (`who: author`): an agent may draft it, and an agent that wrote the person's name
would pass the gate with nobody behind it.

A choice is put to the author: `next` recommends an option where one follows from the
project (the journal's English, the guideline of the design declared), and never picks.

## The JSON

`next --json` prints one object, `manuscript-guard/next/1`, which
[`next.schema.json`](../src/manuscript_guard/contracts/schemas/next.schema.json) describes
and a test holds the output to.

| Field | What it holds |
|---|---|
| `schema` | `manuscript-guard/next/1` |
| `tool_version` | the version of the tool that decided |
| `root` | the project's folder, or the folder read where there is no project |
| `project` | `kind`: `none`, `missing` (the path given is not there, and nothing is offered for its parent), `authors-only`, `unreadable` or `project`; `format`: `markdown` or `latex` (null without a project); `error`: why the project's files could not be read, naming the file (paper.yaml, authors.yaml or another), or that the path is not there |
| `stage` | `current`, the stage decided at (`--stage`, else the one declared); `declared`, the one `paper.yaml` declares, `drafting` where it declares none; `next` (null at `submission`); and the current stage's `description` |
| `counts` | `fail`, `warn`, `info`; `by_gate`, each gate's three counts, G0 to G16 and BUILD always and any other gate a finding names; `deferred`, how many findings start to fail at each later stage |
| `checker` | null, or where a round of co-authors' checks stands: `items`, `outstanding`, `stale`, `disagreements` |
| `notes` | what `next` could not read, in sentences: a part that cannot be read (the co-authors' round, the journal's profile) is left out and said here, and `next` still decides and exits 0 |
| `actions` | what to do, in order |

Each action:

| Field | What it holds |
|---|---|
| `id` | the rule, and for a finding its code or its place (`provenance:bind:manuscript/main.md:42`) |
| `rule`, `tier` | the rule that made it, and its tier |
| `title`, `why` | what to do, and the rule's reason, in a sentence |
| `codes`, `count` | the finding codes it answers, and how many findings |
| `skill` | the skill that deals with it, or null |
| `who` | `agent`, `author` or `ask-author` |
| `command`, `argv` | the command as typed at this system's prompt (quoted for `cmd.exe` on Windows, for a POSIX shell elsewhere), and its words after `manuscript-guard`, which are what runs; null where the skill does the work. On Windows `command` is also null where a word holds `"` beside one of `& \| < > ^ ( )`, which `cmd.exe` cannot be given safely, and only `argv` is said |
| `findings` | the first five findings: `code`, `path` (from the project's folder), `line`, `message` |
| `choice` | null, or `question`, `recommended` (an option's id, or null) and `options` |

Each option of a choice has `id`, `label`, `effect`, `command` (null as an action's is,
for a word `cmd.exe` cannot be given), `argv`, `who` and `placeholders`. A word of `argv` written `<NAME>` is a placeholder for one word, and
`<NAME...>` for one or more, and `placeholders` says what goes there:
`checker build --for <NAME>`, `approve --as <AUTHOR>`, `audit paper.docx --against
<OUTPUTS...>`. A command names the project's folder where `next` was run from another one.

A field added keeps the schema at `/1`. A field renamed or removed, or a value added to a
fixed list (a rule, a `kind`, a `who`), makes it `/2`. Rule ids are not renamed.

## In conversation

The `guide` skill is how an agent uses `next` with the author: at each turn it runs
`next --json`, sums up the stage and the counts in two sentences, puts a due choice to the
author as numbered options, each with its effect and its command, writes a command before
running it and calls `next` again after, and hands each step to the skill the action names. It
never chooses for the author, gives an `author` action to the author, and runs an
`ask-author` command only after a clear yes to that command. The rules `init` writes to
`AGENTS.md` say the same in a paragraph, for an agent tool that has no skills.

Where the agent tool runs the toolkit's hooks, the line at the start of a session, and at
the end of a turn that changed what the gates read, ends with "Next:" and the title of the
first action, decided on the run of the gates the line already reports: the gates run once.

[Back to the README](../README.md)
