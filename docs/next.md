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
| 0 | `cannot-check` | `paper.yaml` cannot be read, or a gate could not run (`gate-errored`, `manuscript-unreadable`, `schema-violation`, `duplicate-key`) |
| 1 | `start` | there is no project: start one, from a paper in the folder where there is one (`init`, `init --from`, `init --latex`, or only `audit`) |
| 2 | `stale-results` | G1 fails: the results are not what the analysis makes now |
| 3 | `plan` | G12 fails: the analysis plan |
| 4 | `choose-journal`, `choose-english`, `choose-guideline`, `choose-study-type` | a choice is due, offered as the `set` commands to pick from |
| 5 | `provenance` | G2, G3, G7 or G8 fails: a number has no source. A number that reads as exactly one published value is offered as its own `bind --apply --only FILE:LINE` |
| 6 | `failures` | everything else that fails, by code |
| 7 | `co-author-checks` | from `internal-review`, a round of co-authors' checks is open: answers outstanding, stale or in disagreement |
| 8 | `warnings` | warnings, one action for each skill |
| 9 | `advance` | nothing fails now: see what the next stage asks (`check --stage <next>`), or move to it (`set stage <next>`) |
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

Every action and every option says who runs it:

- `agent`: an agent may run it;
- `author`: the author decides it, or runs it, as `approve` is the author's own act;
- `ask-author`: an agent runs it only after the author has said yes to that command, as for
  `review --run`, which sends the paper to model providers, or `bind --apply`, which writes
  into the manuscript.

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
| `project` | `kind`: `none`, `authors-only`, `unreadable` or `project`; `format`: `markdown` or `latex` (null without a project); `error`: why `paper.yaml` cannot be read |
| `stage` | `current`, `next` (null at `submission`) and the stage's `description` |
| `counts` | `fail`, `warn`, `info`; `by_gate`, each gate's three counts, G0 to G16 and BUILD always and any other gate a finding names; `deferred`, how many findings start to fail at each later stage |
| `checker` | null, or where a round of co-authors' checks stands: `items`, `outstanding`, `stale`, `disagreements` |
| `notes` | what `next` could not read, in sentences |
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
| `command`, `argv` | the command as written at a prompt, and its words after `manuscript-guard`; null where the skill does the work |
| `findings` | the first five findings: `code`, `path` (from the project's folder), `line`, `message` |
| `choice` | null, or `question`, `recommended` (an option's id, or null) and `options` |

Each option of a choice has `id`, `label`, `effect`, `command`, `argv`, `who` and
`placeholders`. A word of `argv` written `<NAME>` is a placeholder, and `placeholders` says
what goes there: `checker build --for <NAME>`, `approve --as <AUTHOR>`. A command names the
project's folder where `next` was run from another one.

A field added keeps the schema at `/1`. A field renamed or removed, or a value added to a
fixed list (a rule, a `kind`, a `who`), makes it `/2`. Rule ids are not renamed.

[Back to the README](../README.md)
