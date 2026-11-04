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
can read them (`vault check`), the line at each session start, the shell guard, the agent
tool's own deny rules, running the analysis on the real data (`em.vault_input`, `vault run`),
releasing what it wrote (`vault release`), the profile of each file (`em.profile`) and the
synthetic copy drawn from it (`vault synthesize`).

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

## Reading the data in the analysis: `em.vault_input`

The analysis names a file of the vault by its label, never by where it is:

```python
path = em.vault_input("cohort.csv")      # Python
cohort = pd.read_csv(path)
```

```r
path <- em$vault_input("cohort.csv")     # R
cohort <- read.csv(path)
```

Under a run on the real data, where `vault run` sets `MANUSCRIPT_GUARD_VAULT` to the vault's
folder, it gives the real file, declared restricted and recorded in the results as
`vault:cohort.csv` with its digests, never with the folder's path. Anywhere else it gives
`data/synthetic/cohort.csv`, declared synthetic, and refuses where that file is not there,
saying to make one with `vault synthesize` (a later step) or to put one there yourself. So
the agent writes and tests the analysis on the synthetic copy, and the same script, unchanged,
reads the real data when you run it.

## Running on the real data: `vault run`

You run it, at a terminal the agent tool cannot read:

```bash
manuscript-guard vault run                      # every script directly in analysis/, by name
manuscript-guard vault run analysis/02_model.py # or the ones you name, in that order
```

It refuses where standard input is not a terminal, and the plugin's hook refuses it to an
agent. It does this, in order:

1. It copies the project into `<vault>/.runs/<run>/copy/`, inside the vault rather than the
   system's temporary folder, so that the copy shares the data's protection. `.git` and
   `build/` are left out, and so is Python's compiled code in `__pycache__/`, and
   `results/` is emptied. It refuses where `results/` is, or holds, a link or a junction.
2. It lists the scripts it will run, and every script of the copy that changed since the
   run released last, by digest, with the `git diff` command that shows what changed, and
   asks y/N. A script is any file a run can execute or source (`.py`, `.R`, `.Rmd`, `.qmd`,
   `.sh`, a `.lua` filter and the like), wherever it is, but in `results/`, `data/`, a
   `build/` or `.git/` folder at any depth, a hidden folder or a library of others' code,
   as the copy leaves them out; compiled code a run can load (`.pyc`, `.pyd`, `.so`, `.dll`,
   `.dylib`) is listed too. A script you name, and `.Rprofile`, `.Renviron`, `_quarto.yml`,
   `renv/activate.R`, every file of `_extensions/` and a `_metadata.yml` in any folder,
   which a runner reads, are listed wherever they are. The list is read from the copy. For
   each script changed since the run released last, the version that run ran is written
   beside the copy, under `<vault>/.runs/<run>/released/`, from git at that run's commit, and
   the line to read is `git diff --no-index <before> <copy>`: the copy's bytes, which are
   what runs. At your yes the project is digested again, and where a script differs from
   the copy's, the run is refused: run `vault run` again. Read what changed before you
   answer: the scripts were written with an agent, and what they print or write can hold
   any value of the data. On a no, or a Ctrl-C, the copy is removed.
3. It runs the scripts there in order, with `MANUSCRIPT_GUARD_VAULT` set and Python told
   to write no compiled file, and stops at the first that fails.
4. What they print goes to your terminal as it comes, and into `<vault>/.runs/<run>/log.txt`.
5. Where every script finished, it moves everything they wrote into `<vault>/outbox/<run>/`:
   results files, harvested outputs, figures, anything else. A link or a junction a
   script made is left out, and nothing reached through one is moved. The copy of the
   project is then removed. Where the run stops before its end, by a fault or a Ctrl-C, the
   copy is removed too, `log.txt` stays with a `run.json` saying the run did not finish and
   what it had moved, the summary for the agent says it stopped, and such a run is not one
   to release: files moved before the stop may wait in the outbox, and are not released. A second
   Ctrl-C while that is done can leave the copy in the vault: remove it yourself.

The tool writes nothing to the project except `.manuscript-guard/vault/last-run.json`, which
the agent reads to know how the run went. (A script run on the real data runs as your
account, and can write anywhere that account can, the project and the vault included: the
copy keeps it away from the project by where it starts, not by any wall.) The summary holds
each script's exit code and, of a script that failed: for Python, the class of the exception and the frames of its traceback that fall in
the project's own files (path, line, function); for R, the function names of its `Calls:`
line; and the key of a `KeyError` where it is exactly a column name the released profile or
the data dictionary already holds. No message and no value goes in. The project's files are
read as they were before the run: a function whose name is not a word of them, or a frame in
a file the run wrote, is left out, since a script could make either from the data. A class
is named only where it is one of Python's built-in exceptions (`KeyError`, `ValueError`,
`ZeroDivisionError`); any other, a library's or the script's own, is said to be "not a
builtin", with no name and no module, and nothing the summary names is imported. A failing
script can still choose its exit code, which built-in exception it raises, and, among its
own code's names and lines, which frames are reported, at most 20: a few bits for each failed
run. What the summary file holds is read by type, and a field of another type is no name.

## Releasing what a run wrote: `vault release`

```bash
manuscript-guard vault release 20261104-093012 --as "Grace Hopper"
```

You run it, at a terminal; the hook refuses it to an agent. The data custodian releases where
`authors.yaml` names one under `roles:`; otherwise any author does. Before anything is asked,
it reads the outbox:

- every results file whole: each value, each table cell, and the model and variable cards.
  A count from one to below `custodian.minimum_cell_count` refuses the release, unless the
  data custodian has signed off that exact list:
  `manuscript-guard sign --as <custodian> --finding VAULT/custodian/small-counts/<run>`. The
  sign-off, kept in the project, names each results file that holds such a count, and
  neither the count nor where it is; it is bound to the bytes of the run's results files, so
  a run written again needs it again. A count held back that a total beside it gives away
  is a warning;
- each output `harvest.yaml` harvests, every cell, as a site's receipt reads it: a count
  below the minimum refuses;
- a table column whose values are all different, over at least the minimum of rows, is a
  warning: "an identifier, or a value per person?";
- the plan that the run's first results froze, `design/plan.frozen.yaml`, goes in with the
  results where it holds the project's plan and nothing else;
- every other file (a figure, a profile, a CSV no entry harvests, an `.rds`) is a file no
  check reads. Each is listed, and released only where you type its path at the prompt. A
  scatter plot draws real people.

Where `paper.yaml` says `custodian: {restricts_sending: true}`, the release is refused until
the data custodian has signed off that the coding agent's provider may read what is released:
`manuscript-guard sign --as <custodian> --finding VAULT/custodian/agent-reads-releases`. Every
release says so, because it is true: **a file released is read by the coding agent, and
through it by its provider.**

Then it lists what goes into the project and asks y/N. It refuses an outbox holding a link
or a junction, and refuses to write through one in the project, at a file's path or a folder
above it. The results go into `results/`, each
saying in its provenance that it is released, and the rest to their paths. The release is
recorded in `approvals/vault-releases/<run>.json`: who released it and when, the run, each
analysis script by its digest, each file of the vault the results read by its label and
digest, each file released by its digest, and each warning shown. It is your statement,
unsigned, as an approval is.

## What `check` says of results from the vault

G1 compares each input recorded as `vault:<label>` with the digest `design/vault.yaml`
registers, without reading the file:

| Code | Says | Severity |
|---|---|---|
| `vault-input-unregistered` | the results read a label the registry does not hold | a failure |
| `vault-input-changed` | the results read the file with another digest: other data than those registered, as after `vault init --refresh` for a new extract | a failure |
| `vault-result-unreleased` | no release record holds the results file by its digest: copied from the outbox by hand, edited after its release, or written by a run made outside `vault run` | a warning while the paper is written, a failure from `internal-review` on |

Its input is outside the project, so G1 does not say `input-missing` of it.

## What the plugin's hooks refuse

The shell guard, which fires on every shell command of an agent in Claude Code (Bash and
PowerShell) and in Codex:

- refuses `manuscript-guard vault run` and `vault release`, read exactly in either shell's
  words. They are the person's to run. A command that names them in a form the guard cannot
  read exactly, an `echo` or a `bash -c "…"`, is put to the person where a vault is
  registered for the project on this machine, and let through where none is;
- for a command that names the vault's folder, or a path inside it, in any spelling it can
  read (quoted or escaped, either slash, relative to the folder the command is sent from,
  after `=` or `@`, from the home as `~`, `$HOME`, `${HOME}`, `$env:USERPROFILE`,
  `$env:HOME`, `%USERPROFILE%` or `%HOMEDRIVE%%HOMEPATH%`, joined to another path by a colon
  or a semicolon as in a search path or a container's volume, `-v /secure/extract:/data`,
  inside a program the command quotes, `python -c "pd.read_csv('/secure/extract/x.csv')"`,
  from the working folder as `$PWD`, `${PWD}`, `$(pwd)` or `(Get-Location)`, as Git Bash
  writes a drive, `/c/…` or `//c/…`, in any case on Windows and on macOS, or through a link),
  or names `MANUSCRIPT_GUARD_VAULT`: refuses it while this session can read the folder, or
  where that is not found in 3 seconds, and puts it to the person otherwise.

Where `.manuscript-guard/vault.local.yaml` is there and cannot be read, which folder holds the
data is not known, and a command with a slash, a backslash, `~` or `..` in it is refused until
`vault check` or `vault init --refresh`, run at a terminal, puts it right.

The folder is compared as `vault init` was given it and as its links led then, both kept in
`.manuscript-guard/vault.local.yaml`, so that the guard looks nothing of the folder up on
disk. A command's words are compared as written first, which needs no look on disk either;
the looks it does make, at the project's files, at the links of a command's words and at the
folder for the probe, are within the 3 seconds. Past them, a command that names the folder as
written is refused; one whose words were still being followed through their links, in a
project whose vault is known, is refused as one that may name it; one stopped before the vault
was found is let through. On macOS a command that names the
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

## The profile of each file: `em.profile`

`vault init` starts `analysis/00_profile.py` (`.R` where the analysis is in R), unless one is
there already. It reads each registered CSV or TSV file from the folder `vault run` gives it in
`MANUSCRIPT_GUARD_VAULT`, and refuses to run without it. Change its reader to read each file as
the analysis does; a file in another format gets a comment to fill in. The script hands each
table to the emitter:

```python
em.profile(rows, name="cohort.csv", read_as={"header_of": VAULT / "cohort.csv"})
```

```r
em$profile(cohort, name = "cohort.csv", read_as = list(header_of = file.path(vault, "cohort.csv")))
```

`name` is the file's name in the vault. The profile goes to
`profiles/data/cohort.csv.profile.json`. Run by `vault run`, it stays in the vault until a
person releases it: read it before you do, as you would any output. With m the custodian's
minimum cell count from `paper.yaml`, it gives of each column:

- its name, its place, and its type: the data dictionary's where it lists the column, otherwise
  read from the values;
- its missing values, "<m" below m, and their share from m;
- for a coded column (and one the dictionary does not list with 50 values or fewer), each level
  of m rows or more with its count, the rest folded into "other";
- for numbers, dates and times, the rows read, a mean and SD (numbers, from m rows and at least
  three, and only where the rows read are printed: a mean over a count held back would give
  it back, so a column with one to m − 1 missing values, or values that are no number, the
  commonest case, has no mean and no SD), and each centile from the 5th to the 95th that has
  m rows below it and m above it,
  so no centile is the smallest or largest value. Dates to the month, times to the hour;
- for an identifier, a text, or a column the dictionary does not list whose values are all
  different, only its missing values and the pattern its values share ("AA-99999").

Every column's counts add up to the table's rows, and nought is printed as 0, so "<5" is one
to four. Wherever a count is held back behind the minimum, the smallest count printed above
nought is held back beside it (`null`); a reader then knows that one was at least the minimum
and at most the counts printed after it. Where a reader could still work a count out, the
column gives nothing of its counts, its missing values held back too, and says why (`held`).
How many levels "other" folds is said only where it gives no folded level's rows. A table of
fewer rows than the minimum is not profiled. DESIGN.md lists what each field tells a reader.

At a minimum of 1 nothing is held back. With few rows, the centiles, the mean and the SD
together can give the smallest and largest values back: read the profile before releasing it.

`em.profile(..., dataset="visits")` names the data dictionary's dataset the table is; the
profile records it, and the copy reads only that dataset's entries.

`read_as` says how the file is written, for the synthetic copy to be written alike:
`delimiter`, `decimal` ("." or ","), `encoding`, `quoting` ("minimal" or "all"), `newline`,
`dates` (a column's name to its format, made of `%Y %m %d %H %M %S`), and `header_of`, a file
whose header line is read for its delimiter, a byte-order mark and its line ending. Nothing
below the header is read for that. A byte-order mark before the first column's name, as a
reader that keeps it gives it, is taken off the name and recorded; the copy is written with
one only where the file had one. The starter script reads with `utf-8-sig`
(`fileEncoding = "UTF-8-BOM"` in R) and names the file in `header_of`, so the mark is read
off and still recorded.

A level's name and a column's name are shown as written. A column of names, or a level that is
one rare diagnosis's own word, is shown by the profile unless the data dictionary types the
column `text` or `identifier`.

## The synthetic copy: `vault synthesize`

```bash
manuscript-guard vault synthesize            # every profile released
manuscript-guard vault synthesize cohort.csv
```

A column the profile holds back is drawn from the dictionary's codes where it lists them, and
an identifier the dictionary gives a `pattern` is put within it where its released shape
allows; where it does not, the copy says so, naming the column.

It writes `data/synthetic/cohort.csv` from the released profile, the data dictionary and a seed
kept beside the profile, `profiles/data/cohort.csv.synthetic.yaml`, which the first run writes.
It reads nothing else: not the data, not the vault. Anyone may run it, the agent included, and
the shell guard lets it through. The same profile and seed give the same bytes on every machine;
change the seed, or the rows, in that file to draw another copy.

Each column is drawn alone: levels by their counts ("other" as a level named `other`), numbers
and dates along straight lines between the centiles and beyond them, missing values at their
rate, identifiers in their pattern, one to a row, with letters X and the row's number in
their digits, after a 9 where the digits leave one to spare (`XX-90001`), and `SYN` and the
row's number where the pattern has too few digits for the rows.
A row that breaks an order or a unique rule of the data dictionary is drawn again, and after
1000 tries the copy is refused, naming the rule. Since the columns are drawn apart, a model
fitted on the copy finds nothing: the copy is for writing and testing the code, not for results.
A row may still match a real person's by chance.

The copy is written as CSV or TSV. A profile of a `.xlsx`, `.parquet` or `.sas7bdat` file is
refused: export the extract to CSV inside the vault, register that file, and profile it.

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
