# Data held apart from the agent: the vault

The vault is the folder where the data are held, which the operating system keeps from the
agent. The coding agent writes and tests the analysis against a synthetic copy in
`data/synthetic/`. Only a process the person starts reads the real data. The commands are
listed in the [README](../README.md).

Four things are said plainly here, because each is easy to believe otherwise:

- **The operating system decides whether the agent can reach the data**, through a second
  account, a container, permissions or a volume that is not mounted. manuscript-guard does
  not keep the agent out. It registers where the data are and which files they are, checks
  from the agent's own session whether they can be read and says so, and keeps the agent's
  ordinary commands away from the folder.
- **Agent-written code run on the real data can put a row into any output it writes**: a
  "mean" of one chosen patient, a coefficient, a point in a figure, an exit code, the line of
  an error. Rules that count cells do not catch that. A person reading the script, and what
  it wrote, before anything leaves the vault is the control.
- **Nothing here makes a setup lawful** under GDPR, HIPAA or a data-use agreement. Whether a
  setup meets the custodian's terms is for the custodian, the data protection officer or the
  ethics board to say.
- **Data that must stay inside a trusted research environment or a national portal are out
  of scope.** There the agent is usually not inside at all: it writes the code outside
  against synthetic data, the code is run inside, and the environment's own output checks
  apply. That is the site's receipt, `verify --receipt SITE` ([harvest](harvest.md)).

What this version holds: registering the data (`vault init`), checking whether this session
can read them (`vault check`), the line at each session start, the shell guard and the agent
tool's own deny rules. Running the analysis on the real data (`vault run`), releasing what it
wrote (`vault release`), and the profile and synthetic copy are later steps; the shell guard
already refuses `vault run` and `vault release` to an agent.

## Registering the data: `vault init`

The person runs it, at a terminal:

```bash
manuscript-guard vault init /secure/extract cohort.csv "visits/*.csv" --as "Ada Lovelace"
```

The folder comes first, then the files to register in it, by name or by glob from inside the
folder. Only files named are registered: a folder that holds other things is fine, and they
are left out, so that a whole home folder is not taken in by mistake. `--as` names who
registers them.

It refuses, and writes nothing:

- a folder inside the project, or one that holds the project, with links followed. The agent
  works in the project's folder, and a protected folder inside it is easy to get wrong;
- a project whose `paper.yaml` declares no `custodian: {minimum_cell_count: N}`. Every later
  check of what leaves the vault holds counts to it, and custodians differ (5, 10, 11). Where
  the custodian sets no rule, write 1, on purpose;
- a name or glob that matches no file in the folder, and a file whose link leads out of it;
- a project where git would track `.manuscript-guard/vault.local.yaml`.

It writes two files:

- `design/vault.yaml`, to commit. Each file by its label (its path inside the folder, never
  the folder's absolute path), its digests as the emitter takes an input's (`sha256` with line
  endings left out of a text format, `raw_sha256` of the bytes as they are), its size, and who
  registered it and when. No row count: a count is a result.
- `.manuscript-guard/vault.local.yaml`, this machine's: where the folder is. `init` adds
  `.manuscript-guard/` to `.gitignore`. The path is no secret, since knowing it gives no access
  where the operating system keeps the agent out; the hooks need it.

Run it again with the files the vault now holds to add or drop one: a file whose digests have
not changed keeps who registered it and when. After a new extract, `vault init --refresh --as
<you>` digests the registered files again and says which labels changed.

A co-author working from a clone of the project has `design/vault.yaml` and not the local
file. `vault init` with their own copy of the folder registers it on their machine.

## Whether this session can read them: `vault check`

`vault check` opens each registered file for reading and closes it without reading a byte,
and lists the folder, from the process it runs in. It says one of three things:

| Says | Exit | Means |
|---|---|---|
| not reachable from this session | 0 | no registered file could be opened, each refused or not there, and the folder could not be listed or is empty (the mount point of an encrypted volume that is not mounted) |
| readable from this session | 1 | a registered file opened, or the folder lists and holds something (the files moved or renamed): the account this runs as can read what is in it |
| not registered here | 2 | this machine has no `.manuscript-guard/vault.local.yaml` |

It asks the operating system by trying, not by `os.access`, which on Windows reads the
read-only attribute and not the access control list.

Run by the agent, it answers for the agent's account. That is the point of it: the plugin's
session-start hook runs the same probe, in the agent tool's own process, and adds one line to
the session's context. Where the folder can be read, the line says that the separation the
vault relies on is not in place, tells the agent to work on `data/synthetic/` and not to read
the folder or name it in a command, and is shown to the person as well. Where it cannot be
reached, a shorter line says so. The probe gives up after 5 seconds, and the line then says
the answer was not found.

The probe measures the account and the process it runs in. It sees nothing of a sandbox an
agent tool applies only to the commands the agent runs in a shell: the hook runs outside it,
so an agent under the same account in such a sandbox is reported readable.

## What the plugin's hooks refuse

The shell guard, which fires on every shell command of an agent in Claude Code (Bash and
PowerShell) and in Codex:

- refuses `manuscript-guard vault run` and `vault release`, read exactly in either shell's
  words. They are the person's to run. A command that names them in a form the guard cannot
  read exactly, an `echo` or a `bash -c "…"`, is put to the person;
- for a command that names the vault's folder, or a path inside it, in any spelling it can
  read (quoted or escaped, either slash, relative to the folder the command is sent from,
  after `=` or `@`, from the home as `~`, `$HOME`, `${HOME}`, `$env:USERPROFILE`,
  `$env:HOME`, `%USERPROFILE%` or `%HOMEDRIVE%%HOMEPATH%`, joined to another path by a colon
  or a semicolon as in a search path or a container's volume, `-v /secure/extract:/data`, as
  Git Bash writes a drive, `/c/…`, in any case on Windows and on macOS, or through a link),
  or names `MANUSCRIPT_GUARD_VAULT`: refuses it while this session can read the folder, or
  where that is not found in 3 seconds, and puts it to the person otherwise.

The folder is compared as `vault init` was given it and as its links led then, both kept in
`.manuscript-guard/vault.local.yaml`, so that the guard looks nothing of the folder up on
disk; each look it does make, at the project's files, at the links of a command's words and
at the folder for the probe, is within the 3 seconds. On macOS a command that names the
folder in another case is refused even on a volume that tells cases apart, the safe way
round.

Where the agent tool cannot put a question to the person (Codex, as of the versions read),
what would be asked is refused.

It reads the words of ordinary commands. A path built while the command runs, held in a
variable of the agent's own, or computed by a script, is not seen; neither is a command that
names a folder above the vault and reads down into it, `grep -r … /secure`, nor one that
moves first and names the vault from there, `cd .. && cat study-data/cohort.csv`, since a
word is read from the folder the command is sent from. It is a guard against an agent's
ordinary commands, not against a deliberate evasion.

There is no hook on the agent's file-reading tools (Read, Grep, Glob): it would start a Python
process on every read, for everyone who has the plugin, vault or none. The agent tool's own
rules do that job, at no cost.

## The agent tool's own deny rules

`vault init` prints Claude Code's deny rules for the folder:

```text
Read(//c/secure/extract)
Read(//c/secure/extract/**)
Edit(//c/secure/extract)
Edit(//c/secure/extract/**)
```

`//` begins an absolute path from the root of the file system, and on Windows Claude Code puts
a path in POSIX form before it matches one, `C:\secure\extract` being `/c/secure/extract`
(its permissions documentation, read 2026-10-30). On macOS or Linux the same folder at
`/secure/extract` is `//secure/extract`.

A mapped drive keeps the letter you typed (`Z:\…`), which a rule can name, beside the share
its link leads to, which it cannot; a folder reached through a link gets rules for both.

`vault init --agent-settings` writes them into `.claude/settings.local.json` in the project,
under `permissions.deny`, after you answer y at a terminal; without a terminal it says what it
wrote, the vault's two files, and that the rules were not. Where it creates the settings file
it adds it to `.gitignore`, since it holds this machine's paths; where git tracks it, the
command is refused before anything is written. `vault init --agent-settings` alone writes them
for the vault already registered.
Claude Code reads that file in a session started in the project's folder; where the project
is a folder inside a larger repository and sessions start at its root, put the rules where
Claude Code's settings documentation says that session looks.
A folder whose path holds a character a rule reads as a pattern (`*`, `?`, `[`, `]`, a
backslash, a bracket) gets no rules; nor does one on a network share.

What these rules cover is Claude Code's to say, and it says: its own file tools, the file
commands it recognises in a shell (`cat`, `head`, `tail`, `sed`, `tee`) and the targets of
redirections. Not a command that reads files without naming them, and not a script that opens
a file itself. They are a second layer, not the separation. Other agent tools have rules of
their own, or none; see their documentation.

## Four setups, most separating first

1. **The agent in a container** (a dev container, Docker) that mounts the project and not the
   data. The person's terminal on the host reads the data. `vault check` from the agent's
   session says "not reachable".
2. **The agent under a second operating-system account** that has no right to the folder. On
   Windows, deny that account read access to the folder with `icacls`; on macOS or Linux, own
   the folder with the person's account and give it mode 700.
3. **The data on an encrypted volume mounted only while the person runs on it**, with no agent
   session open meanwhile. The session-start line says "cannot be reached" while it is
   unmounted.
4. **One account and nothing else.** Here the tool can only keep the agent's ordinary path
   away from the folder: `vault check` says "readable" at every session start, and the shell
   guard refuses commands that name the folder. This is a working convention, not separation.
   Whether it satisfies the custodian's terms is for the custodian to say.

## Three traps

- **WSL mounts the Windows drives** under `/mnt/c/…` unless automount is turned off in
  `/etc/wsl.conf`. An agent in WSL then reaches a folder that the Windows account rules were
  meant to keep, through a path the guard does not read as the folder.
- **An agent app's own terminal panel can be read by the agent.** The Claude desktop app's can.
  Run what reads the data in a terminal the agent tool cannot read, a separate terminal window
  of the operating system, not a panel beside the conversation.
- **An IDE's terminal beside an agent extension** needs the same thought: the extension may read
  the terminal's output, and what the run prints there.

What the tool does not check is written down, with the rest of its limits, in
[DESIGN.md](../DESIGN.md) under "Known gaps".
