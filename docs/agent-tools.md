# Agent tools: Claude Code, Codex and the others

The pip package is the whole guarantee. This page is about the optional part: the skills
and hooks an agent tool can load, how each tool installs and updates them, and what each
one does and does not enforce. The fourteen skills are listed in the
[README](../README.md#the-claude-code-plugin).

## The Claude Code plugin (optional)

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
nothing.

**Four hooks**, and what each is for:

| Hook | What it does |
|---|---|
| session start | One line: the stage, and how many findings fail and warn. Where a file of the project cannot be used, which file and why, in place of that line. And once, when the installed tool is older than the plugin, a notice with the upgrade command |
| before a write | Refuses edits to `results/`, `build/` and generated checklist profiles. These are written by something else, and editing one desynchronises it |
| after a write | For a manuscript file, classifies the numbers just saved and names any bound to nothing, while you are still in the paragraph. For an analysis file, says the results are now stale and the Methods may no longer describe the code |
| before a submission-shaped shell command | Runs the submission check and blocks if it fails, or if a file of the project cannot be used and the check cannot run |

The submission guard matches against the **whole command string** rather than a prefix rule,
because `cd example && manuscript-guard submit` and `FOO=1 manuscript-guard submit` both
defeat prefix matching. That is not hypothetical: it is how a submission slipped past the
guard in the project this one learned from. It reads a command whichever tool runs it
(`Bash`, `PowerShell` or `Monitor` under Claude Code), and knows the PowerShell words for
its verbs, `Compress-Archive` and `Send-MailMessage` among them.

The command is held to the project at the folder the agent is in. Where that folder has
none, as at the root of a repository with the paper in a folder below, it is held to each
project the command names: `cd example && manuscript-guard submit`, `manuscript-guard submit
example` and `scp example/build/manuscript.docx host:` are all checked against `example`. A
project the command does not name is left alone, and a folder held in a variable is not
followed.

A hook never breaks a session. Anything unexpected exits silently, because a guard that
crashes on a half-configured project gets removed, taking the guards that worked with it.
A project file that cannot be used, because it does not parse or is not UTF-8, is not
unexpected: `check` names it in a sentence, and the submission guard and the session start
pass that sentence on. A manuscript file that is not UTF-8 is a failing finding of the check
like any other, and the guard blocks on it. Outside a project they say nothing.

## Codex (optional)

Codex installs the same plugin from this repository, with the same fourteen skills and the
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
| before a submission-shaped shell command | As above |

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

## Gemini CLI, Mistral Vibe, Kimi Code CLI and other agent tools (optional)

By their own documentation, these tools read skills from a folder, `.agents/skills`, in your
home or in a project. After the pip package, one command copies the fourteen skills there:

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

How far this has been checked: Gemini CLI 0.58.0 lists the fourteen skills from a project's
`.agents/skills`. That it reads the folder in your home, and that Mistral Vibe and Kimi Code
CLI read either, is from their own documentation and has not been watched. What each tool
does with `AGENTS.md` is from its documentation too, and for Kimi Code CLI that documentation
was not found to say. No skill has been used in a session of any of the three.

[Back to the README](../README.md)
