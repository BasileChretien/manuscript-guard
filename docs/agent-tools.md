# Agent tools: Claude Code, Codex and the others

This page is about the part that is optional: the skills and hooks an agent tool can load,
how each tool installs and updates them, and what each one does and does not enforce. The
fifteen skills are listed in the [README](../README.md#the-claude-code-plugin).

## The Claude Code plugin

The pip package is the whole guarantee and needs nothing else. The plugin adds the parts
that need judgement — setting up a project, drafting, literature verification, figure
review, review panels, answering reviewers — plus hooks that catch mistakes at the moment
they are made.

This repository is its own plugin marketplace. Install once, and the skills and hooks are
there in every project you open:

```bash
claude plugin marketplace add BasileChretien/manuscript-guard
claude plugin install manuscript-guard@manuscript-guard
```

A local clone works as the source too: `claude plugin marketplace add /path/to/manuscript-guard`.
Restart Claude Code afterwards. Skills are namespaced, so they appear as
`/manuscript-guard:project-setup` and so on, and Claude also picks them up by description
without being asked.

The plugin is installed as a copy, so a new version of a skill reaches you only when you
ask for it:

```bash
claude plugin marketplace update manuscript-guard
claude plugin update manuscript-guard@manuscript-guard
```

To work on the skills themselves, load the directory for one session instead, and edits
apply on the next start: `claude --plugin-dir ./plugin`.

The hooks call `manuscript-guard-hook`, so the pip package has to be on the `PATH` that
Claude Code sees. Outside a manuscript-guard project they find no `paper.yaml` and do
nothing, but for the submission guard where a command names a project (below).

**Four hooks**, and what each is for:

| Hook | What it does |
|---|---|
| session start | One line: the stage, and how many findings fail and warn. Where a file of the project cannot be used, which file and why, in place of that line. And once, when the installed tool is older than the plugin, a notice with the upgrade command |
| before a write | Refuses edits to `results/`, `build/` and generated checklist profiles. These are written by something else, and editing one desynchronises it. Puts to you an edit of `literature/attested.yaml` that names an attester, or changes one, and an edit of an author's approval or a named person's sign-off under `approvals/` |
| after a write | For a manuscript file, classifies the numbers just saved and names any bound to nothing, while you are still in the paragraph. For an analysis file, says the results are now stale and the Methods may no longer describe the code |
| before a submission-shaped shell command | Runs the submission check and blocks if it fails, or if a file of the project cannot be used and the check cannot run. Puts to you a `review --run --yes`, which would send the manuscript without asking, an `approve`, which only the author approving can run, and a `sign`, which only the person `authors.yaml` names for the role can run |

**Four decisions are put to you, not taken by the agent.** Sending the manuscript to model
providers without being asked, `review --run --yes`, naming who attested a value read in a
source, `attested_by`, an author's approval of the manuscript, `approve`, and a named
person's sign-off of a finding, `sign`, are statements only that person can make. Before any
of them runs, the
hook answers "ask": Claude Code shows you the call and the reason, auto mode included, and
it goes ahead only if you approve it. The reason names the models in `review.models`, or the
attester the edit adds. An edit that leaves the attesters as they were, a value or a date
changed beside them, is not put to you, nor a run with `--dry-run` or without `--yes`, which
asks you itself. Under `claude -p`, with nobody to answer, the call is refused.

The submission guard matches against the **whole command string** rather than a prefix rule,
because `cd example && manuscript-guard submit` and `FOO=1 manuscript-guard submit` both
defeat prefix matching. That is not hypothetical: it is how a submission slipped past the
guard in the project this one learned from. It reads a command whichever tool runs it
(`Bash`, `PowerShell` or `Monitor` under Claude Code), and knows the PowerShell words for
its verbs, `Compress-Archive` and `Send-MailMessage` among them. It knows the command by
each name it is installed or run under (`manuscript-guard`, `mguard`, and
`python -m manuscript_guard.cli`), and holds a build asked for at the submission stage,
`build --stage submission`, as it holds `build --submission`.

The command is held to the project at the folder the agent is in, and to each other
project it names by a path. So from the root of a repository with the paper in a folder
below, `cd example && manuscript-guard submit`, `manuscript-guard submit example` and `scp
example/build/manuscript.docx host:` are all checked against `example`, and from inside
one paper `cd ../second && manuscript-guard submit` is checked against both. A project the
command does not name is left alone, and a folder held in a variable is not followed.

A hook never breaks a session. Anything unexpected exits silently, because a guard that
crashes on a half-configured project gets removed, taking the guards that worked with it.
A project file that cannot be used, because it does not parse or is not UTF-8, is not
unexpected: `check` names it in a sentence, and the submission guard and the session start
pass that sentence on. A manuscript file that is not UTF-8 is a failing finding of the check
like any other, and the guard blocks on it. Outside a project they say nothing, with one
exception: the submission guard holds a command to a project the command names by a path,
as `cd paper && manuscript-guard submit` does when it is sent from the folder above.

### Whether each skill fires when it should

`evals/`, beside the plugin rather than in it so that installing the plugin copies none of
it, holds the cases `claude plugin eval` runs against a copy of this checkout's plugin.
Each case is a prompt and its graders:

- **routing:** a request each skill is for;
- **near-miss:** a request that sounds like one skill's neighbour and is not;
- **negative:** a request no skill of ours is for;
- **proportionality:** a small request that must not start a skill's whole workflow.

The routing cases also carry a judged outcome, so a run with and without the plugin shows
what each skill adds over the model alone.

The suite is run by hand, never by pytest or CI. Tests never call a provider, and an agent
never decides pass or fail. It needs Claude Code 2.1.269 or later. The two proportionality
cases grant Bash, which on Windows runs only under WSL2. `claude plugin eval` reads a suite
only from inside the plugin it runs, so `tools/run_skill_evals.py` copies the plugin and the
suite into a folder of their own and runs it there, with the report kept local. A routing
case whose prompt speaks of a project, "my analysis script", starts in a copy of the worked
example: the script puts one beside the cases, the case's `scaffold.sh` copies it in, and the
script passes `--scaffold` for that. From the repository's root, the arguments after `--`
going to `claude plugin eval`:

```bash
python tools/run_skill_evals.py -- --ablation with-without --runs 3 --model <model> --max-cost-usd <budget>
```

A run is paid at API prices, or counts against a subscription's usage, and is 168 runs at
the size chosen (28 cases, 3 runs, 2 arms): run one case once first (`-- --case <name>
--runs 1 --ablation none`) to measure it. The results and the report are written to a new
folder under `evals/results/`, which git ignores, and not into the copy, which is deleted when
the run ends; the script chooses the folder, and refuses `--output-dir`. The copy is of the working tree as it is: record a run made on a clean checkout. Record each run's date, model and
result in DESIGN.md, and run it again whenever a pull request changes a skill's name or
description.

## Codex

Codex installs the same plugin from this repository, with the same fifteen skills and the
same four hooks. After the pip package:

```bash
codex plugin marketplace add BasileChretien/manuscript-guard
codex plugin add manuscript-guard@manuscript-guard
```

Neither command needs a login. Start a new Codex session afterwards. Both need the `codex`
command line tool; the desktop app on its own may not put it on your `PATH`.

Codex keeps a copy of the plugin, as Claude Code does. For the install above, from GitHub,
one command takes a new release, refreshing the marketplace and the installed plugin with
it:

```bash
codex plugin marketplace upgrade manuscript-guard
```

Upgrade the pip package at the same time. Codex may also refresh the copy without being
asked: its program carries an automatic upgrade of marketplaces, and when that runs was not
observed. Either way, when the plugin is the newer of the two, the session-start hook says
so once.

**Codex runs a hook only after you have trusted it.** By Codex's documentation, it warns at
the start of a session that hooks are waiting for review, and `/hooks` is where you read and
trust them: there are four, each a `manuscript-guard-hook` command. Until you do, nothing is
caught at the moment of the mistake. `check` and `build` run every gate either way.

| Hook | Under Codex |
|---|---|
| session start | As above |
| before a write | Codex edits files by applying a patch, which may write several files. A patch that adds or changes a file in `results/`, `build/` or a generated checklist profile, or moves a file into one, is refused whole, and the reason names those files. A patch that only deletes one is not refused |
| after a write | Each manuscript file in the patch that holds an unbound number, and each analysis file, gets its line |
| before a submission-shaped shell command | As above, except a `review --run --yes`, which is refused (below) |

**Under Codex the two decisions are refused, not asked.** Codex reads a hook's "ask" and does
not support it yet: by its documentation it marks the hook as failed and lets the call go
through. So where the hook cannot tell that Claude Code sent the event, it refuses the call
with the same reason, and you run the command or make the edit yourself. Claude Code is told
apart by what it gives a hook (`CLAUDE_PROJECT_DIR`, and an event with no `turn_id`, which
Codex sends with every tool call); any other tool is refused, the direction in which you are
not bypassed.

What Codex does not enforce. `check`, `build` and `submit` hold whatever the hooks do:

- By its documentation, a hook you have not trusted, or one whose definition changed since
  you trusted it, is skipped.
- The write guard sees a patch. A file written by a shell command is not seen, as under
  Claude Code.
- Codex's own documentation calls tool hooks "a useful guardrail, not a complete enforcement
  boundary", and says some tool paths can opt out of them.

How far this has been checked. Seen: the install, from GitHub by hand and from a checkout on
every pull request; the upgrade taking an installed copy from one release to the next; and
the hooks answering input shaped as Codex's source builds it. Not seen, because it needs a
login: a Codex session in which a skill is loaded, a hook is trusted or a hook fires. That
includes the session-start notice, which depends on Codex telling the hook where the plugin
is, as its documentation says it does.

## Gemini CLI, Mistral Vibe, Kimi Code CLI and other agent tools

By their own documentation, these tools read skills from a folder, `.agents/skills`, in your
home or in a project. After the pip package, one command copies the fifteen skills there:

```bash
manuscript-guard install-skills              # for you, in every project: ~/.agents/skills
manuscript-guard install-skills --project    # for one paper: .agents/skills in that project
```

Start a new session of the agent tool afterwards. `--dir <folder>` copies them anywhere
else, for a tool that reads another folder.

**It never writes over what it did not write.** The folder in your home is shared with every
other skill you have. A skill of yours with the same name as one of these is left as it is
and named, the others are copied, and the command exits 1; `--project` copies into the
paper's own folder, where nothing else is. A copied skill you have edited since is left too:
to take the new release of it, delete its folder and run the command again. What the command
may replace is recorded in a stamp beside the skills, `.manuscript-guard.json`. Leave it
there, and commit it with the skills if you commit them. If the command cannot read it, it
stops and touches nothing.

**To update,** upgrade the pip package and run the same command again. Until you do, `check`
and `build` say so: when a copy in either folder is from another release than the tool, one
line follows their own output, with the command to run.

**To check or remove them,** add `--verify` or `--remove` to the same command, with the same
`--project` or `--dir` if you gave one:

```bash
manuscript-guard install-skills --verify            # which copied skills are as they were copied
manuscript-guard install-skills --remove --dry-run  # what would be removed
manuscript-guard install-skills --remove            # remove them, then the stamp
```

`--verify` changes nothing. `--remove` takes away each skill whose files are still as they
were copied, then the stamp. A skill you have edited is named and left, and the stamp is
kept with that skill alone in it; delete it yourself if it should go.

**There are no hooks under these tools.** Nothing is caught at the moment of the mistake.
`check`, `build` and `submit` hold as they do everywhere, so an edited results file or an
unbound number is reported when one of them next runs.

| | Skills | `AGENTS.md` | Hooks |
|---|---|---|---|
| Claude Code | plugin | read where there is no `CLAUDE.md` | four |
| Codex | plugin | read | four, once you have trusted them |
| Gemini CLI | copy | read once a setting lists it | none |
| Mistral Vibe | copy | read in a folder you have trusted | none |
| Kimi Code CLI | copy | not confirmed | none |

For Gemini CLI the setting is `context.fileName`, in `.gemini/settings.json` of the project
or of your home:

```json
{ "context": { "fileName": ["AGENTS.md", "GEMINI.md"] } }
```

A Codex user without the `codex` command can use the copy in place of the plugin, and then
has no hooks. With both, Codex has every skill in two places it reads, the plugin and the
folder. What it then shows was not watched.

How far this has been checked: Gemini CLI 0.58.0 listed the skills from a project's
`.agents/skills`, all fourteen that were there when it was run. That it reads the folder in your home, and that Mistral Vibe and Kimi Code
CLI read either, is from their own documentation and has not been watched. What each tool
does with `AGENTS.md` is from its documentation too, and for Kimi Code CLI that documentation
was not found to say. No skill has been used in a session of any of the three.

## AGENTS.md

Among the files `manuscript-guard init` writes is an `AGENTS.md`: the rules of the project
on one short page, for any agent working in it. Going by each tool's own documentation,
Codex reads that file on its own, Mistral Vibe does in a folder you have trusted, and Claude
Code (2.1.277 or later) does where there is no `CLAUDE.md` in the project or above it.
Gemini CLI reads it once `context.fileName` in its settings lists `AGENTS.md`. None of this
has been watched in a session. It is advice to the reader; the gates are what holds.

[Back to the README](../README.md)
